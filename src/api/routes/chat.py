"""RAG-backed chat streaming routes."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import config
from src.api.db import get_db
from src.api.deps import log_audit_event, require_permission
from src.api.models import ChatMessage, ChatSession
from src.api.rate_limit import limiter
from src.api.rag_service import (
    SYSTEM_PROMPT,
    finalize_answer_for_question,
    get_rag_pipeline,
    prepare_formal_context,
    prepare_quickcode_context,
    prepare_retrieved_context,
    resolve_effective_index_mode,
)
from src.api.schemas.chat import ChatRequest
from src.auth.users import User
from src.rag.pipeline import DebugInfo

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)

MODEL_ALIAS = {
    "gemma4": "vllm:gemma-4-26b-a4b-nvfp4",
    "nemotron": "vllm:nemotron-3-nano-30b-a3b-nvfp4",
    "gpt-oss": "sglang:gpt-oss-20b",
    "qwen3": "sglang:qwen3-30b-a3b-instruct-2507-fp8",
}


@router.post("/stream")
@limiter.limit("20/minute")
async def chat_stream(
    chat_request: ChatRequest,
    request: Request = None,
    user: User = Depends(require_permission("chat.stream")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream a real RAG answer and persist the completed turn."""

    chat_session = await _ensure_session(db, user.username, chat_request.session_id, chat_request.query)
    history = await _load_history(db, chat_session.id)

    async def event_generator():
        llm_stream = None
        chunks = []
        sources: list[dict] = []
        graph_payload = None
        warnings: list[dict] = []
        deterministic_answer: str | None = None
        debug_info: DebugInfo | None = None
        tokens: list[str] = []
        selected_model = _select_model(chat_request)
        effective_index_mode = resolve_effective_index_mode(chat_request.query, chat_request.index_mode)
        started = time.perf_counter()
        try:
            yield _sse("status", "searching")
            pipeline = _get_pipeline(selected_model, chat_request.top_k, effective_index_mode)
            system_prompt = SYSTEM_PROMPT
            doc_filter = None
            if chat_request.mode == "quickcode":
                chunks, sources, prompt, system_prompt, doc_filter = await prepare_quickcode_context(
                    pipeline,
                    chat_request.query,
                    chat_request.filters,
                )
            elif chat_request.mode == "formal":
                chunks, sources, prompt, doc_filter = await prepare_formal_context(
                    pipeline,
                    chat_request.query,
                    chat_request.top_k,
                    history,
                    chat_request.filters,
                    chat_request.memo,
                )
            else:
                chunks, sources, prompt, graph_payload, warnings, deterministic_answer, debug_info = await prepare_retrieved_context(
                    pipeline,
                    chat_request.query,
                    chat_request.top_k,
                    history,
                    chat_request.filters,
                )
            yield _sse("sources", sources)
            if graph_payload is not None:
                logger.info(
                    "chat graph payload review_paths=%s exclusions=%s",
                    [path.get("path_type") for path in graph_payload.get("graph_review_paths", [])],
                    [path.get("exclusion_reasons") for path in graph_payload.get("graph_review_paths", [])],
                )
                yield _sse("graph", graph_payload)
            for warning in warnings:
                yield _sse("warning", warning)

            if deterministic_answer is not None:
                for token in _chunk_text(deterministic_answer):
                    tokens.append(token)
                    yield _sse("token", {"t": token})
                    await asyncio.sleep(0)
            else:
                llm_stream = _generate_llm_stream(
                    pipeline.llm,
                    prompt,
                    system_prompt,
                    chat_request.temperature,
                    chat_request.reasoning_mode,
                )
                for token in llm_stream:
                    tokens.append(token)
                    yield _sse("token", {"t": token})
                    await asyncio.sleep(0)
                for warning in _llm_safety_warnings(pipeline.llm):
                    warnings.append(warning)
                    yield _sse("warning", warning)

            raw_answer = "".join(tokens).strip()
            if not raw_answer:
                empty_warning = {
                    "code": "EMPTY_LLM_OUTPUT",
                    "message": "모델 응답 본문이 비어 있어 답변을 생성하지 못했습니다.",
                }
                yield _sse("warning", empty_warning)
                answer = "모델 응답 본문이 비어 있어 답변을 생성하지 못했습니다. 검색 근거를 다시 확인해 주세요."
            else:
                answer = finalize_answer_for_question(chat_request.query, raw_answer, chunks, graph_payload)
            yield _sse("final", {"answer": answer})
            yield _sse("done", {"session_id": chat_session.id, "answer": answer})
            await _persist_turn(
                db,
                chat_session.id,
                chat_request.query,
                answer,
                sources,
                graph_payload=graph_payload,
                warnings=warnings,
            )
            await log_audit_event(
                db,
                "CHAT_QUERY",
                user_id=user.username,
                ip_address=_client_ip(request),
                detail={
                    "model": selected_model,
                    "mode": chat_request.mode,
                    "search_type": (
                        (chat_request.filters or {}).get("search_type")
                        if chat_request.mode == "formal"
                        else None
                    ),
                    "top_k": chat_request.top_k,
                    "temperature": chat_request.temperature,
                    "reasoning_mode": chat_request.reasoning_mode,
                    "reasoning_supported": bool(getattr(pipeline.llm, "last_reasoning_supported", False)),
                    "reasoning_filtered": bool(getattr(pipeline.llm, "last_reasoning_filtered", False)),
                    "finish_reason": getattr(pipeline.llm, "last_finish_reason", None),
                    "final_retry_finish_reason": getattr(pipeline.llm, "last_final_retry_finish_reason", None),
                    "warning_codes": [warning.get("code") for warning in warnings if warning.get("code")],
                    "index_mode": chat_request.index_mode,
                    "effective_index_mode": effective_index_mode,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    "session_id": chat_session.id,
                    "source_count": len(sources),
                    "query_preview": chat_request.query.strip()[:200],
                    "doc_filter": doc_filter,
                    "rag_diagnostics": _build_rag_diagnostics(
                        question=chat_request.query,
                        model=selected_model,
                        index_mode=chat_request.index_mode,
                        effective_index_mode=effective_index_mode,
                        debug=debug_info,
                        source_count=len(sources),
                        warnings=warnings,
                        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
                    ) if chat_request.mode == "general" else None,
                    "request_id": getattr(getattr(request, "state", None), "request_id", None),
                },
            )
        except asyncio.CancelledError:
            await _close_stream(llm_stream)
            raise
        except Exception as exc:
            await _close_stream(llm_stream)
            yield _sse("error", {"code": "CHAT_STREAM_FAILED", "message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/quickcode")
@limiter.limit("50/minute")
async def chat_quickcode(
    chat_request: ChatRequest,
    request: Request = None,
    user: User = Depends(require_permission("chat.stream")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream a quick code search response."""

    return await chat_stream(chat_request.copy(update={"mode": "quickcode"}), request, user, db)


@router.post("/formal")
@limiter.limit("30/minute")
async def chat_formal(
    chat_request: ChatRequest,
    request: Request = None,
    user: User = Depends(require_permission("chat.stream")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream a formal policy-filtered response."""

    return await chat_stream(chat_request.copy(update={"mode": "formal"}), request, user, db)


def _select_model(request: ChatRequest) -> str:
    if request.model:
        return MODEL_ALIAS.get(request.model, request.model)
    if request.provider == "openai":
        return config.OPENAI_DEFAULT_MODEL
    return config.OLLAMA_MODEL


def _get_pipeline(model: str, top_k: int, index_mode: str):
    if index_mode == "default":
        return get_rag_pipeline(model, top_k)
    return get_rag_pipeline(model, top_k, index_mode)


def _llm_safety_warnings(llm) -> list[dict]:
    warnings = getattr(llm, "last_safety_warnings", None)
    if not isinstance(warnings, list):
        return []
    normalized: list[dict] = []
    seen: set[str] = set()
    for warning in warnings:
        if not isinstance(warning, dict):
            continue
        code = str(warning.get("code") or "")
        if code and code in seen:
            continue
        if code:
            seen.add(code)
        normalized.append(warning)
    return normalized


def _generate_llm_stream(llm, prompt: str, system_prompt: str, temperature: float, reasoning_mode: str):
    signature = inspect.signature(llm.generate_stream)
    if "reasoning_mode" in signature.parameters:
        return llm.generate_stream(
            prompt,
            system=system_prompt,
            temperature=temperature,
            reasoning_mode=reasoning_mode,
        )
    return llm.generate_stream(prompt, system=system_prompt, temperature=temperature)


def _client_ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


def _sse(event: str, data) -> str:
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _chunk_text(text: str, size: int = 32):
    """Yield deterministic answers through the same token SSE path."""

    for start in range(0, len(text), size):
        yield text[start:start + size]


def _build_rag_diagnostics(
    *,
    question: str,
    model: str,
    index_mode: str,
    effective_index_mode: str,
    debug: DebugInfo | None,
    source_count: int,
    warnings: list[dict],
    elapsed_ms: float,
) -> dict:
    dense_hits = list(getattr(debug, "dense_hits", []) or [])
    bm25_hits = list(getattr(debug, "bm25_hits", []) or [])
    rrf_hits = list(getattr(debug, "rrf_hits", []) or [])
    final_hits = list(getattr(debug, "final_hits", []) or [])
    search_intent = getattr(debug, "search_intent", None) if debug is not None else None
    search_intent_payload = search_intent.to_payload() if hasattr(search_intent, "to_payload") else None
    retrieval_execution = getattr(debug, "retrieval_execution", None) if debug is not None else None
    retrieval_execution_payload = (
        retrieval_execution.to_payload() if hasattr(retrieval_execution, "to_payload") else None
    )
    graph_result = getattr(debug, "graph_result", None) if debug is not None else None
    graph_plan = getattr(graph_result, "plan", None) if graph_result is not None else None
    return {
        "query_preview": question.strip()[:200],
        "model": model,
        "index_mode": index_mode,
        "effective_index_mode": effective_index_mode,
        "warnings": warnings,
        "normalized_terms": dict(getattr(graph_plan, "normalized_terms", {}) or {}),
        "term_correction_candidates": list(getattr(graph_plan, "term_correction_candidates", []) or []),
        "ambiguous_terms": list(getattr(graph_plan, "ambiguous_terms", []) or []),
        "clarification_questions": list(getattr(graph_plan, "clarification_questions", []) or []),
        "search_intent": search_intent_payload,
        "retrieval_execution": retrieval_execution_payload,
        "graph_review_path_count": len(getattr(graph_result, "review_paths", []) or []) if graph_result is not None else 0,
        "steps": [
            {
                "key": "query_preprocess",
                "label": "쿼리 전처리",
                "result": question.strip()[:200],
                "elapsed_ms": None,
                "status": "done",
            },
            {
                "key": "intent_classification",
                "label": "검색 의도 분류",
                "result": _format_search_intent_result(search_intent_payload, retrieval_execution_payload),
                "elapsed_ms": None,
                "status": "done" if search_intent_payload else "empty",
            },
            _build_hit_step(
                "bm25",
                "BM25 키워드 검색",
                bm25_hits,
                executed=(retrieval_execution_payload or {}).get("bm25_executed"),
            ),
            _build_hit_step(
                "dense",
                "임베딩 벡터 검색",
                dense_hits,
                executed=(
                    (retrieval_execution_payload or {}).get("dense_filtered_executed")
                    or (retrieval_execution_payload or {}).get("dense_general_executed")
                ),
            ),
            _build_hit_step("rrf", "후보 융합", rrf_hits),
            _build_hit_step("final", "최종 검색 후보", final_hits, source_count=source_count),
            {
                "key": "llm",
                "label": "LLM 답변 생성",
                "result": f"{model} / 출처 {source_count}건 / 경고 {len(warnings)}건",
                "elapsed_ms": elapsed_ms,
                "status": "done",
            },
        ],
    }


def _format_search_intent_result(intent: dict | None, execution: dict | None = None) -> str:
    if not intent:
        return "결과 없음"
    if execution:
        fallback = execution.get("fallback_reason")
        suffix = f" / {fallback}" if fallback else ""
        return (
            f"{intent.get('intent')} / "
            f"적용 BM25 {execution.get('applied_bm25_weight')} · "
            f"Chroma {execution.get('applied_dense_weight')} / "
            f"filtered_dense={execution.get('dense_filtered_executed')} · "
            f"general_dense={execution.get('dense_general_executed')}{suffix}"
        )
    return (
        f"{intent.get('intent')} / "
        f"BM25 {intent.get('bm25_weight')} · Chroma {intent.get('dense_weight')} / "
        f"skip_general_dense={intent.get('skip_general_dense')}"
    )


def _build_hit_step(
    key: str,
    label: str,
    hits: list,
    *,
    source_count: int | None = None,
    executed: bool | None = None,
) -> dict:
    hit_count = len(hits)
    top_score = getattr(hits[0], "score", None) if hits else None
    top_doc = getattr(hits[0], "doc_short", "") if hits else ""
    result = f"{hit_count}건"
    if hit_count and top_score is not None:
        result += f" (상위 스코어 {top_score})"
    if top_doc:
        result += f" / {top_doc}"
    if source_count is not None:
        result += f" / 출처 {source_count}건"
    return {
        "key": key,
        "label": label,
        "result": result if hit_count else ("건너뜀" if executed is False else "결과 없음"),
        "elapsed_ms": None,
        "status": "done" if hit_count else ("skipped" if executed is False else "empty"),
    }


async def _ensure_session(
    db: AsyncSession,
    username: str,
    session_id: str | None,
    query: str,
) -> ChatSession:
    if session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == username)
        )
        chat_session = result.scalar_one_or_none()
        if chat_session is not None:
            return chat_session

        logger.info("Ignoring stale chat session id for user %s: %s", username, session_id)

    return await _create_session(db, username, query)


async def _create_session(db: AsyncSession, username: str, query: str) -> ChatSession:
    title = query.strip()[:40] or "새로운 보상 질의"
    chat_session = ChatSession(user_id=username, title=title)
    db.add(chat_session)
    await db.commit()
    await db.refresh(chat_session)
    return chat_session


async def _load_history(db: AsyncSession, session_id: str) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    )
    return list(result.scalars())


async def _persist_turn(
    db: AsyncSession,
    session_id: str,
    query: str,
    answer: str,
    sources: list[dict],
    graph_payload: dict | None = None,
    warnings: list[dict] | None = None,
) -> None:
    persisted_sources = list(sources)
    if graph_payload is not None or warnings:
        persisted_sources.append(
            {
                "__kind": "assistant_meta",
                "graph_result": graph_payload,
                "warnings": warnings or [],
            }
        )
    db.add_all(
        [
            ChatMessage(session_id=session_id, role="user", content=query, sources=None),
            ChatMessage(session_id=session_id, role="assistant", content=answer, sources=persisted_sources),
        ]
    )
    await db.commit()


async def _close_stream(stream) -> None:
    if stream is None:
        return
    aclose = getattr(stream, "aclose", None)
    if aclose is not None:
        result = aclose()
        if inspect.isawaitable(result):
            await result
        return
    close = getattr(stream, "close", None)
    if close is not None:
        close()
