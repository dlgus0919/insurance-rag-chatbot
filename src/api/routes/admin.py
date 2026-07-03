"""Admin routes backed by SQLite audit and message data."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from statistics import mean

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src import config
from src.api.db import get_db
from src.api.deps import require_admin, require_permission
from src.api.exceptions import DuplicateEntryException, UserNotFoundException, ValidationException
from src.api.models import AuditLog, ChatMessage
from src.api.rate_limit import limiter
from src.api.schemas.admin import (
    AdminUserCreateRequest,
    AdminUserCreateResponse,
    AdminUserListResponse,
    AdminUserPatchRequest,
    AdminUserResponse,
    PasswordResetRequest,
    PasswordResetResponse,
)
from src.auth import users as user_store
from src.auth.users import User
from src.graph.vector_sync import build_report, check_evidence_sync, load_evidence_rows
from src.llm.factory import is_ollama_allowed, list_available_models
from src.retrieval.index_mode import (
    INDEX_MODES,
    USER_FACING_DEFAULT_ALIASES,
    USER_FACING_DEFAULT_INDEX_MODE,
    resolve_index_paths,
)
from src.retrieval.vector_store import VectorStore

router = APIRouter(prefix="/admin", tags=["admin"])


def _active_admin_users() -> list[User]:
    return [
        user
        for user in user_store.list_users()
        if user.role == user_store.ROLE_ADMIN and user.status == "active"
    ]


def _guard_admin_account_mutation(
    target: User,
    current: User,
    *,
    next_role: str | None = None,
    next_status: str | None = None,
) -> None:
    is_admin_after = (next_role or target.role) == user_store.ROLE_ADMIN
    is_active_after = (next_status or target.status) == "active"
    removes_admin_access = target.role == user_store.ROLE_ADMIN and (not is_admin_after or not is_active_after)
    if not removes_admin_access:
        return

    if target.username == current.username:
        raise ValidationException(detail="현재 로그인한 관리자 계정은 비활성화, 역할 변경 또는 삭제할 수 없습니다.")

    active_admin_count = len(_active_admin_users())
    if target.status == "active" and active_admin_count <= 1:
        raise ValidationException(detail="마지막 활성 관리자 계정은 비활성화, 역할 변경 또는 삭제할 수 없습니다.")


GRAPH_TABLES = (
    "graph_nodes",
    "graph_edges",
    "graph_evidence",
    "graph_aliases",
    "graph_node_evidence",
    "graph_edge_evidence",
)


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _warning_code(warning) -> str:
    if isinstance(warning, dict):
        return str(warning.get("code") or warning.get("message") or "UNKNOWN_WARNING")
    return str(warning or "UNKNOWN_WARNING")


def _query_issue_item(item: AuditLog, detail: dict, **extra) -> dict:
    payload = {
        "created_at": item.created_at.isoformat(),
        "user_id": item.user_id,
        "query_preview": detail.get("query_preview") or detail.get("question") or "",
        "model": detail.get("model") or "-",
        "mode": detail.get("mode") or "unknown",
        "session_id": detail.get("session_id"),
    }
    payload.update(extra)
    return payload


def _build_model_quality_stats(rows: dict[str, dict]) -> list[dict]:
    stats = []
    for row in rows.values():
        total_attempts = int(row["total_attempts"] or 0)
        success_count = int(row["success_count"] or 0)
        failure_count = int(row["failure_count"] or 0)
        elapsed_values = row["elapsed_values_ms"]
        citation_checked = int(row["citation_checked_count"] or 0)
        citation_missing = int(row["citation_missing_count"] or 0)
        stats.append({
            "model": row["model"],
            "total_attempts": total_attempts,
            "success_count": success_count,
            "failure_count": failure_count,
            "error_rate": round(failure_count / total_attempts, 4) if total_attempts else 0.0,
            "avg_elapsed_sec": round(mean(elapsed_values) / 1000, 2) if elapsed_values else None,
            "citation_checked_count": citation_checked,
            "citation_missing_count": citation_missing,
            "citation_missing_rate": round(citation_missing / citation_checked, 4) if citation_checked else None,
        })
    return sorted(stats, key=lambda item: (-item["total_attempts"], item["model"]))


def _graph_manifest_path() -> Path:
    graph_path = config.GRAPH_INDEX_PATH
    return graph_path.with_name(f"{graph_path.stem}_manifest.json")


def _read_graph_manifest_file() -> dict:
    manifest_path = _graph_manifest_path()
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"manifest_read_error": str(exc)}


def _read_graph_db_status() -> dict:
    graph_path = config.GRAPH_INDEX_PATH
    if not graph_path.exists():
        return {}

    table_counts = {}
    manifest_rows = {}
    try:
        with sqlite3.connect(f"file:{graph_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            for table in GRAPH_TABLES:
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                    table_counts[table] = int(row["count"] if row else 0)
                except sqlite3.Error:
                    table_counts[table] = None
            try:
                rows = conn.execute("SELECT key, value FROM graph_build_manifest").fetchall()
                manifest_rows = {str(row["key"]): row["value"] for row in rows}
            except sqlite3.Error:
                manifest_rows = {}
    except sqlite3.Error as exc:
        return {"db_read_error": str(exc)}

    return {
        "table_counts": table_counts,
        "db_manifest": manifest_rows,
    }


@router.get("/logs")
@limiter.limit("60/minute")
async def logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_permission("admin.logs")),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """Return paginated audit logs newest first."""

    total = await db.scalar(select(func.count(AuditLog.id)))
    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
        "items": [
            {
                "id": item.id,
                "user_id": item.user_id,
                "event_type": item.event_type,
                "ip_address": item.ip_address,
                "detail": item.detail or {},
                "created_at": item.created_at.isoformat(),
            }
            for item in result.scalars()
        ],
    }


@router.get("/stats")
async def stats(
    _: User = Depends(require_permission("admin.stats")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate dashboard stats from messages and audit logs."""

    query_rows = await db.execute(
        select(AuditLog)
        .where(AuditLog.event_type.in_(["CHAT_QUERY", "CHAT_QUERY_FAILED"]))
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    )
    query_logs = list(query_rows.scalars())
    successful_query_logs = [item for item in query_logs if item.event_type == "CHAT_QUERY"]
    total_queries = len(successful_query_logs)
    total_answers = int(
        await db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.role == "assistant"))
        or 0
    )
    mode_distribution = Counter()
    user_distribution = Counter()
    model_distribution = Counter()
    elapsed_values_ms: list[float] = []
    source_counts: list[int] = []
    daily_distribution = Counter()
    warning_code_distribution = Counter()
    ambiguous_term_distribution = Counter()
    failed_queries = []
    warning_queries = []
    ambiguous_queries = []
    total_warning_count = 0
    warning_query_count = 0
    ambiguity_query_count = 0
    clarification_question_count = 0
    model_quality: dict[str, dict] = {}

    for item in query_logs:
        detail = item.detail or {}
        model = str(detail.get("model") or "?")
        model_row = model_quality.setdefault(
            model,
            {
                "model": model,
                "total_attempts": 0,
                "success_count": 0,
                "failure_count": 0,
                "elapsed_values_ms": [],
                "citation_checked_count": 0,
                "citation_missing_count": 0,
            },
        )
        model_row["total_attempts"] += 1
        diagnostic = detail.get("rag_diagnostics") or {}
        warnings = _as_list(detail.get("warnings")) or _as_list(diagnostic.get("warnings"))
        ambiguous_terms = _as_list(detail.get("ambiguous_terms")) or _as_list(diagnostic.get("ambiguous_terms"))
        clarification_questions = (
            _as_list(detail.get("clarification_questions"))
            or _as_list(diagnostic.get("clarification_questions"))
        )

        if item.event_type == "CHAT_QUERY_FAILED" or detail.get("status") == "failed" or detail.get("error_code"):
            model_row["failure_count"] += 1
            failed_queries.append(
                _query_issue_item(
                    item,
                    detail,
                    error_code=detail.get("error_code") or "CHAT_QUERY_FAILED",
                    error_message=detail.get("error_message") or detail.get("message") or "",
                )
            )

        if warnings:
            warning_query_count += 1
            total_warning_count += len(warnings)
            for warning in warnings:
                warning_code_distribution[_warning_code(warning)] += 1
            warning_queries.append(
                _query_issue_item(
                    item,
                    detail,
                    warnings=warnings[:3],
                    warning_count=len(warnings),
                )
            )

        if ambiguous_terms or clarification_questions:
            ambiguity_query_count += 1
            clarification_question_count += len(clarification_questions)
            for term in ambiguous_terms:
                ambiguous_term_distribution[str(term)] += 1
            ambiguous_queries.append(
                _query_issue_item(
                    item,
                    detail,
                    ambiguous_terms=ambiguous_terms,
                    clarification_questions=clarification_questions[:3],
                )
            )

        if item.event_type != "CHAT_QUERY":
            continue
        model_row["success_count"] += 1
        mode_distribution[str(detail.get("mode") or "unknown")] += 1
        user_distribution[str(item.user_id or "(unknown)")] += 1
        model_distribution[model] += 1
        elapsed = detail.get("elapsed_ms")
        if isinstance(elapsed, (int, float)):
            elapsed_values_ms.append(float(elapsed))
            model_row["elapsed_values_ms"].append(float(elapsed))
        source_count = detail.get("source_count")
        if isinstance(source_count, int):
            source_counts.append(source_count)
            model_row["citation_checked_count"] += 1
            if source_count <= 0:
                model_row["citation_missing_count"] += 1
        daily_distribution[str(item.created_at.date())] += 1

    for mode in ("general", "quickcode", "formal"):
        mode_distribution.setdefault(mode, 0)

    return {
        "total_queries": total_queries,
        "total_answers": total_answers,
        "avg_elapsed_sec": round(mean(elapsed_values_ms) / 1000, 2) if elapsed_values_ms else 0.0,
        "avg_source_count": round(mean(source_counts), 2) if source_counts else 0.0,
        "mode_distribution": dict(mode_distribution),
        "user_distribution": dict(user_distribution),
        "model_distribution": dict(model_distribution),
        "model_quality_stats": _build_model_quality_stats(model_quality),
        "daily_usage": [
            {"date": date, "count": int(count)}
            for date, count in sorted(daily_distribution.items(), key=lambda item: item[0])
        ],
        "issue_stats": {
            "failed_query_count": len(failed_queries),
            "warning_query_count": warning_query_count,
            "total_warning_count": total_warning_count,
            "ambiguity_query_count": ambiguity_query_count,
            "clarification_question_count": clarification_question_count,
            "warning_code_distribution": dict(warning_code_distribution),
            "ambiguous_term_distribution": dict(ambiguous_term_distribution),
            "recent_failures": list(reversed(failed_queries))[:5],
            "recent_warnings": list(reversed(warning_queries))[:5],
            "recent_ambiguities": list(reversed(ambiguous_queries))[:5],
        },
    }


@router.get("/system-summary")
async def system_summary(
    _: User = Depends(require_permission("admin.stats")),
) -> dict:
    """Return admin-facing runtime and index asset summary."""

    index_rows = []
    for key, label in (
        ("default", "기본 운영 인덱스"),
        ("v2_only", "보정본 OCR만"),
        ("v1_v2_combined", "원본+보정본 OCR 통합"),
    ):
        bm25_path, chroma_dir = resolve_index_paths(key)
        index_rows.append(
            {
                "key": key,
                "label": label,
                "bm25_path": str(bm25_path),
                "bm25_exists": bm25_path.exists(),
                "chroma_dir": str(chroma_dir),
                "chroma_exists": chroma_dir.exists(),
                "chroma_sqlite_exists": (chroma_dir / "chroma.sqlite3").exists(),
            }
        )

    return {
        "status": "ok" if any(row["bm25_exists"] or row["chroma_exists"] for row in index_rows) else "degraded",
        "assets": {
            "chunks": config.CHUNKS_PATH.exists(),
            "graph": config.GRAPH_INDEX_PATH.exists(),
            "relational": config.STANDARD_CODES_DB_PATH.exists(),
            "users": True,
        },
        "indices": index_rows,
        "llm": {
            "ollama_allowed": is_ollama_allowed(),
            "default_local_model": config.OLLAMA_MODEL,
            "default_openai_model": config.OPENAI_DEFAULT_MODEL,
            "default_vllm_model": config.VLLM_DEFAULT_MODEL,
            "default_sglang_model": config.SGLANG_DEFAULT_MODEL,
            "available_models": list_available_models(),
        },
        "embedding": {
            "model": config.EMBEDDING_MODEL,
            "hf_model_download": config.HF_MODEL_DOWNLOAD,
            "cloud_deploy": config.CLOUD_DEPLOY,
        },
    }


@router.get("/graph-sync-status")
async def graph_sync_status(
    _: User = Depends(require_permission("admin.stats")),
) -> dict:
    """Return the latest GraphDB build/sync execution status."""

    graph_path = config.GRAPH_INDEX_PATH
    manifest_path = _graph_manifest_path()
    manifest_file = _read_graph_manifest_file()
    db_status = _read_graph_db_status()
    db_manifest = db_status.get("db_manifest") or {}
    effective_manifest = {**db_manifest, **manifest_file}
    read_error = db_status.get("db_read_error") or manifest_file.get("manifest_read_error")
    available = graph_path.exists() and not read_error
    table_counts = db_status.get("table_counts") or {}
    loaded_rows = {
        "nodes": table_counts.get("graph_nodes"),
        "edges": table_counts.get("graph_edges"),
        "evidence": table_counts.get("graph_evidence"),
        "aliases": table_counts.get("graph_aliases"),
        "node_evidence_links": table_counts.get("graph_node_evidence"),
        "edge_evidence_links": table_counts.get("graph_edge_evidence"),
    }
    manifest_counts = {
        "nodes": effective_manifest.get("node_count"),
        "edges": effective_manifest.get("edge_count"),
        "evidence": effective_manifest.get("evidence_count"),
        "aliases": effective_manifest.get("alias_count"),
    }

    status_label = "success" if available and (manifest_file or db_manifest) else "unknown"
    if read_error:
        status_label = "error"
    elif not graph_path.exists():
        status_label = "missing"
    technical_errors = [read_error] if read_error else []
    pipeline_success = status_label == "success"

    return {
        "available": available,
        "status": status_label,
        "pipeline_success": pipeline_success,
        "message": (
            "GraphDB build manifest and table counts loaded."
            if status_label == "success"
            else "GraphDB sync/build status is not available."
        ),
        "sync_target": "sqlite_property_graph",
        "operation_summary": {
            "nodes_loaded": loaded_rows["nodes"],
            "edges_loaded": loaded_rows["edges"],
            "evidence_loaded": loaded_rows["evidence"],
            "aliases_loaded": loaded_rows["aliases"],
            "node_evidence_links_loaded": loaded_rows["node_evidence_links"],
            "edge_evidence_links_loaded": loaded_rows["edge_evidence_links"],
            "technical_error_count": len(technical_errors),
            "technical_errors": technical_errors,
            "network_error_count": None,
            "network_error_applicable": False,
        },
        "metric_note": (
            "현재 GraphDB 빌드 파이프라인은 마지막 실행의 최종 적재 카운트를 manifest/DB에서 제공합니다. "
            "증분 created/updated 카운트와 네트워크 에러 카운트는 별도 run log가 추가되어야 정확히 집계됩니다."
        ),
        "graph_path": str(graph_path),
        "graph_exists": graph_path.exists(),
        "graph_size_bytes": graph_path.stat().st_size if graph_path.exists() else 0,
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest_path.exists(),
        "build_date": effective_manifest.get("build_date"),
        "source_mode": effective_manifest.get("source_mode"),
        "chunks_path": effective_manifest.get("chunks_path"),
        "standard_code_db": effective_manifest.get("standard_code_db"),
        "manifest": effective_manifest,
        "manifest_counts": manifest_counts,
        "loaded_rows": loaded_rows,
        "table_counts": table_counts,
        "read_error": read_error,
    }


@router.get("/rag-diagnostics/latest")
async def latest_rag_diagnostics(
    _: User = Depends(require_permission("admin.stats")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the latest persisted general-query RAG diagnostic snapshot."""

    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.event_type == "CHAT_QUERY",
            func.json_extract(AuditLog.detail, "$.mode") == "general",
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(1)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return {
            "available": False,
            "message": "아직 일반 질의의 검색 진단 데이터가 없습니다.",
        }

    detail = item.detail or {}
    diagnostic = detail.get("rag_diagnostics") or _build_fallback_rag_diagnostic(detail)
    diagnostic["available"] = True
    diagnostic["created_at"] = item.created_at.isoformat()
    diagnostic["user_id"] = item.user_id
    diagnostic["request_id"] = detail.get("request_id")
    return diagnostic


@router.get("/graph-vector-sync")
async def graph_vector_sync(
    index_mode: str = Query(default="default"),
    limit: int = Query(default=300, ge=1, le=2000),
    seed: int = Query(default=20260531),
    _: User = Depends(require_permission("admin.stats")),
) -> dict:
    """Return a sampled GraphDB evidence to VectorStore sync diagnostic."""

    requested_mode = (index_mode or "default").strip().lower()
    if requested_mode in USER_FACING_DEFAULT_ALIASES:
        normalized_mode = USER_FACING_DEFAULT_INDEX_MODE
    elif requested_mode in INDEX_MODES:
        normalized_mode = requested_mode
    else:
        raise ValidationException(f"지원하지 않는 인덱스 모드입니다: {index_mode}")

    graph_path = config.GRAPH_INDEX_PATH
    _, chroma_dir = resolve_index_paths(normalized_mode)
    if not graph_path.exists():
        return {
            "available": False,
            "message": "GraphDB 파일이 없습니다.",
            "graph_path": str(graph_path),
            "index_mode": normalized_mode,
        }
    if not (chroma_dir / "chroma.sqlite3").exists():
        return {
            "available": False,
            "message": "Chroma 인덱스가 없습니다.",
            "chroma_dir": str(chroma_dir),
            "index_mode": normalized_mode,
        }

    rows = load_evidence_rows(graph_path, limit=limit, seed=seed)
    store = VectorStore(chroma_dir)
    results = check_evidence_sync(rows, store.collection)
    report = build_report(
        graph_path=graph_path,
        chroma_dir=chroma_dir,
        index_mode=normalized_mode,
        rows=rows,
        results=results,
        example_limit=10,
    )
    report["available"] = True
    return report


@router.get("/users", response_model=AdminUserListResponse)
@limiter.limit("100/minute")
async def list_admin_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    role: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    _: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> AdminUserListResponse:
    """Return paginated users from users.json."""

    items = [_admin_user_response(user) for user in user_store.list_users()]
    if role:
        items = [item for item in items if item.role == role]
    if status_filter:
        items = [item for item in items if item.status == status_filter]
    if search:
        needle = search.casefold()
        items = [
            item
            for item in items
            if needle in item.id.casefold()
            or needle in item.username.casefold()
            or needle in (item.email or "").casefold()
        ]

    total = len(items)
    start = (page - 1) * page_size
    return AdminUserListResponse(total=total, page=page, page_size=page_size, items=items[start : start + page_size])


@router.post("/users", response_model=AdminUserCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("100/minute")
async def create_admin_user(
    payload: AdminUserCreateRequest,
    _: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> AdminUserCreateResponse:
    """Create a users.json-backed account."""

    try:
        created = user_store.add_user(
            payload.user_id,
            payload.password,
            payload.role,
            payload.username,
            email=payload.email,
        )
    except user_store.UserStoreError as exc:
        if "이미 존재" in str(exc):
            raise DuplicateEntryException(detail=str(exc)) from exc
        raise ValidationException(detail=str(exc)) from exc

    response = _admin_user_response(created)
    payload = response.model_dump() if hasattr(response, "model_dump") else response.dict()
    return AdminUserCreateResponse(**payload, message="사용자가 정상 생성되었습니다.")


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
@limiter.limit("100/minute")
async def update_admin_user(
    user_id: str,
    payload: AdminUserPatchRequest,
    current: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> AdminUserResponse:
    """Update account profile, role, or status."""

    target = user_store.get_user(user_id)
    if target is None:
        raise UserNotFoundException(detail=f"사용자를 찾을 수 없습니다: {user_id}")

    _guard_admin_account_mutation(
        target,
        current,
        next_role=user_store._normalize_role(payload.role) if payload.role is not None else None,
        next_status=payload.status,
    )

    try:
        updated = user_store.update_user(
            user_id,
            display_name=payload.username,
            email=payload.email,
            role=payload.role,
            status=payload.status,
        )
    except user_store.UserStoreError as exc:
        if "찾을 수 없습니다" in str(exc):
            raise UserNotFoundException(detail=str(exc)) from exc
        raise ValidationException(detail=str(exc)) from exc
    return _admin_user_response(updated)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("100/minute")
async def delete_admin_user(
    user_id: str,
    current: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> Response:
    """Permanently delete a users.json-backed account."""

    target = user_store.get_user(user_id)
    if target is None:
        raise UserNotFoundException(detail=f"사용자를 찾을 수 없습니다: {user_id}")

    _guard_admin_account_mutation(target, current, next_role="user", next_status="inactive")

    try:
        user_store.delete_user(user_id)
    except user_store.UserStoreError as exc:
        if "찾을 수 없습니다" in str(exc):
            raise UserNotFoundException(detail=str(exc)) from exc
        raise ValidationException(detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/reset-password", response_model=PasswordResetResponse)
@limiter.limit("100/minute")
async def reset_admin_user_password(
    user_id: str,
    payload: PasswordResetRequest,
    _: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> PasswordResetResponse:
    """Reset a user's password."""

    try:
        user_store.reset_password(user_id, payload.new_password)
    except user_store.UserStoreError as exc:
        if "찾을 수 없습니다" in str(exc):
            raise UserNotFoundException(detail=str(exc)) from exc
        raise ValidationException(detail=str(exc)) from exc
    return PasswordResetResponse(message="비밀번호가 정상 재설정되었습니다.", user_id=user_id)


def _admin_user_response(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.username,
        username=user.display_name,
        email=user.email,
        role=user_store.external_role(user.role),
        status=user.status,
        last_login=user.last_login,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _build_fallback_rag_diagnostic(detail: dict) -> dict:
    query_preview = str(detail.get("query_preview") or "(최근 질의 미상)")
    model = str(detail.get("model") or "?")
    source_count = int(detail.get("source_count") or 0)
    elapsed_ms = float(detail.get("elapsed_ms") or 0.0)
    return {
        "query_preview": query_preview,
        "model": model,
        "index_mode": detail.get("index_mode") or "default",
        "effective_index_mode": detail.get("effective_index_mode") or detail.get("index_mode") or "default",
        "warnings": [],
        "steps": [
            {
                "key": "query_preprocess",
                "label": "쿼리 전처리",
                "result": query_preview,
                "elapsed_ms": None,
                "status": "done",
            },
            {
                "key": "retrieval",
                "label": "검색 후보 결합",
                "result": f"출처 {source_count}건",
                "elapsed_ms": None,
                "status": "done" if source_count > 0 else "empty",
            },
            {
                "key": "llm",
                "label": "LLM 답변 생성",
                "result": model,
                "elapsed_ms": elapsed_ms,
                "status": "done",
            },
        ],
    }
