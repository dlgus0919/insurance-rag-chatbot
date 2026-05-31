"""Admin routes backed by SQLite audit and message data."""

from __future__ import annotations

from collections import Counter
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
from src.retrieval.index_mode import INDEX_MODES, resolve_index_paths
from src.retrieval.vector_store import VectorStore

router = APIRouter(prefix="/admin", tags=["admin"])


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
        .where(AuditLog.event_type == "CHAT_QUERY")
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    )
    query_logs = list(query_rows.scalars())
    total_queries = len(query_logs)
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

    for item in query_logs:
        detail = item.detail or {}
        mode_distribution[str(detail.get("mode") or "unknown")] += 1
        user_distribution[str(item.user_id or "(unknown)")] += 1
        model_distribution[str(detail.get("model") or "?")] += 1
        elapsed = detail.get("elapsed_ms")
        if isinstance(elapsed, (int, float)):
            elapsed_values_ms.append(float(elapsed))
        source_count = detail.get("source_count")
        if isinstance(source_count, int):
            source_counts.append(source_count)
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
        "daily_usage": [
            {"date": date, "count": int(count)}
            for date, count in sorted(daily_distribution.items(), key=lambda item: item[0])
        ],
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

    normalized_mode = (index_mode or "default").strip().lower()
    if normalized_mode not in INDEX_MODES:
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

    if user_id == "admin":
        if payload.status is not None and payload.status != "active":
            raise ValidationException(detail="admin 계정은 비활성화할 수 없습니다.")
        if payload.role is not None and payload.role != "admin":
            raise ValidationException(detail="admin 계정의 역할은 변경할 수 없습니다.")

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

    if user_id == "admin":
        raise ValidationException(detail="admin 계정은 삭제할 수 없습니다.")
    if user_id == current.username:
        raise ValidationException(detail="자기 자신의 계정은 삭제할 수 없습니다.")

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
