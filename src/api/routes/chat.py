"""RAG-backed chat streaming routes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
import json
import logging
import time
import unicodedata
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import config
from src.api.db import get_db
from src.api.isolated_e2e import is_isolated_e2e_run
from src.api.deps import log_audit_event, require_permission
from src.api.models import ChatMessage, ChatSession
from src.api.public_payloads import (
    assistant_metadata,
    public_graph_payload,
    public_sources,
    public_warnings,
    storage_sources,
)
from src.api.rate_limit import limiter
from src.api.rag_service import (
    SYSTEM_PROMPT,
    finalize_answer_for_question,
    graph_payload_has_renderable_evidence,
    get_rag_pipeline,
    prepare_formal_context,
    prepare_quickcode_context,
    prepare_retrieved_context,
    resolve_effective_index_mode,
)
from src.api.routes.claim import _claim_response_text, _claim_snapshot_source
from src.api.schemas.chat import ChatRequest
from src.api.schemas.claim import ClaimCalculationRequest, ClaimCalculationResponse, ClaimItemRequest
from src.auth.users import User
from src.ontology.registry import get_default_ontology_registry
from src.rag.auto_params import TOPK_STRATEGY_RULE, AutoRagParams, resolve_auto_rag_params
from src.rag.conversation_context import (
    ConversationQueryScope,
    ConversationState,
    finalize_assertion_source,
    parse_conversation_state,
    resolve_conversation_context,
    serialize_conversation_state,
    state_with_pending_clarification,
)
from src.rag.evidence_assessment import clarification_slots_from_payload
from src.rag.pipeline import DebugInfo
from src.rag.query_router import resolve_query_route
from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput
from src.claim_calculation.pipeline import run_claim_calculation
from src.claim_calculation.thread_context import extract_claim_snapshots
from src.claim_calculation.thread_recalculation import (
    apply_special_status_override,
    build_recalculation_payload,
    detect_recalculation_intent,
    find_target_lines,
    needs_special_calculation_clarification,
    line_payable_amount,
    money_text,
    select_claim_snapshot,
    special_status_from_query,
    snapshot_payable_amount,
)

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)

MODEL_ALIAS = {
    "gemma4": "vllm:gemma-4-26b-a4b-nvfp4",
    "nemotron": "vllm:nemotron-3-nano-30b-a3b-nvfp4",
    "gpt-oss": "sglang:gpt-oss-20b",
    "qwen3": "sglang:qwen3-30b-a3b-instruct-2507-fp8",
}


@dataclass
class _ClaimFollowUpResult:
    answer: str
    sources: list[dict] = field(default_factory=list)
    action: str = ""
    status: str = ""
    item_count: int | None = None
    requires_review: bool | None = None


@router.get("/documents")
async def chat_documents(
    user: User = Depends(require_permission("chat.stream")),
) -> dict[str, list[dict[str, str]]]:
    """Return document filters available to the chat UI."""

    return {"documents": _document_filter_options()}


def _normalized_source_identifier(value: str | None) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip()


def _registered_pdf_source(*, doc_short: str | None, filename: str | None) -> config.PdfSource | None:
    """Resolve a configured PDF source without accepting a user-supplied path."""

    requested_doc_short = _normalized_source_identifier(doc_short)
    requested_filename = _normalized_source_identifier(filename)
    if not requested_doc_short and not requested_filename:
        return None
    if requested_filename and ("/" in requested_filename or "\\" in requested_filename):
        return None

    matches: list[config.PdfSource] = []
    for source in config.PDF_SOURCES:
        if requested_doc_short and requested_doc_short != _normalized_source_identifier(source.doc_short):
            continue
        if requested_filename and requested_filename != _normalized_source_identifier(source.path.name):
            continue
        matches.append(source)

    if len(matches) != 1:
        return None
    source = matches[0]
    if source.path.suffix.casefold() != ".pdf" or not source.path.is_file():
        return None
    return source


@router.get("/sources/pdf")
async def chat_source_pdf(
    doc_short: str | None = Query(default=None, max_length=240),
    filename: str | None = Query(default=None, max_length=512),
    user: User = Depends(require_permission("chat.stream")),
) -> FileResponse:
    """Return an allowlisted registered source PDF for an authenticated chat user."""

    source = _registered_pdf_source(doc_short=doc_short, filename=filename)
    if source is None:
        raise HTTPException(status_code=404, detail="등록된 원문 PDF를 찾을 수 없습니다.")
    return FileResponse(
        source.path,
        media_type="application/pdf",
        filename=source.path.name,
        content_disposition_type="inline",
    )


def _document_filter_options() -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for source in config.PDF_SOURCES:
        seen.setdefault(
            source.doc_short,
            {
                "doc_short": source.doc_short,
                "doc_name": source.doc_name,
                "doc_type": source.doc_type,
            },
        )
    for source in config.SPREADSHEET_SOURCES:
        doc_short = source.doc_short or source.source_name
        seen.setdefault(
            doc_short,
            {
                "doc_short": doc_short,
                "doc_name": source.source_name,
                "doc_type": source.data_type,
            },
        )
    return list(seen.values())


async def _handle_claim_follow_up(
    *,
    chat_session_id: str,
    query: str,
    history: list[ChatMessage],
    selected_model: str,
    index_mode: str,
) -> _ClaimFollowUpResult | None:
    intent = detect_recalculation_intent(query)
    if intent is None:
        return None

    snapshots = extract_claim_snapshots(history)
    snapshot, clarification = select_claim_snapshot(snapshots, query)
    if snapshot is None:
        return _ClaimFollowUpResult(clarification, action=intent.action, status="clarification")
    if intent.needs_clarification:
        return _ClaimFollowUpResult(
            "어떤 기준으로 보상할지 명확하지 않습니다. 급여 본인부담/비급여/3대비급여 중 하나를 포함해 다시 질문해 주세요. "
            "예: '비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요.'",
            action=intent.action,
            status="clarification",
        )

    matches = find_target_lines(snapshot, intent.target_text)
    if not matches:
        return _ClaimFollowUpResult(
            _target_not_found_answer(snapshot, intent.target_text),
            action=intent.action,
            status="clarification",
        )
    if len(matches) > 1:
        return _ClaimFollowUpResult(
            _ambiguous_target_answer(matches),
            action=intent.action,
            status="clarification",
        )

    target_line = matches[0]
    if intent.action == "not_covered":
        answer, source = _not_covered_answer_and_source(snapshot, target_line)
        return _ClaimFollowUpResult(
            answer,
            [source],
            action=intent.action,
            status="conditional_not_covered",
            item_count=len(((snapshot.get("result") or {}).get("line_results") or [])),
            requires_review=True,
        )

    special_status_override = special_status_from_query(query)
    if needs_special_calculation_clarification(snapshot, intent, target_line) and not special_status_override:
        return _ClaimFollowUpResult(
            "5세대 3대비급여 재계산에는 산정특례 적용 여부가 필요합니다. "
            "'산정특례 적용으로' 또는 '산정특례 미적용으로' 중 하나를 함께 알려주세요.",
            action=intent.action,
            status="clarification",
        )

    payload_data = build_recalculation_payload(snapshot, intent, target_line)
    payload_data = apply_special_status_override(payload_data, special_status_override)
    payload = ClaimCalculationRequest(
        session_id=chat_session_id,
        save_to_history=False,
        items=[ClaimItemRequest(**item) for item in payload_data["items"]],
        context=payload_data.get("context") or {},
        model=selected_model,
        provider=_provider_from_model_id(selected_model),
        index_mode=index_mode if index_mode in {"v2_only", "v1_v2_combined"} else "v2_only",
    )
    context_data = _recalculation_context_data(payload, payload_data)
    warnings: list[str] = []
    if is_isolated_e2e_run():
        pipeline = None
    else:
        try:
            pipeline = _get_pipeline(selected_model, config.CLAIM_RAG_TOP_K, payload.index_mode)
        except Exception as exc:
            pipeline = None
            warnings.append("RAG 근거 초기화에 실패하여 구조화 계산만 수행했습니다.")
            logger.warning("Claim follow-up RAG initialization failed: %s", exc)
    result = run_claim_calculation(
        rag_pipeline=pipeline,
        items=[
            ClaimItemInput(
                line_id=item.line_id or f"line-{idx + 1}",
                input_name=item.input_name,
                input_code=item.input_code,
                claimed_amount=item.claimed_amount,
                insured_copay_amount=item.insured_copay_amount,
                nonpay_amount=item.nonpay_amount,
                quantity=item.quantity,
                user_category_hint=item.user_category_hint,
                extra_info=item.extra_info,
            )
            for idx, item in enumerate(payload.items)
        ],
        context=ClaimCaseContext(**context_data),
        basis_mode=payload.basis_mode,
        selected_basis_docs=payload.selected_basis_docs,
        use_fake_planner=payload.use_fake_planner,
        model_id=selected_model.split(":", 1)[1] if ":" in selected_model else selected_model,
        provider=payload.provider or _provider_from_model_id(selected_model),
    )
    response = ClaimCalculationResponse.from_result(result, warnings)
    sources = list(response.applied_basis or []) + [_claim_snapshot_source(payload, response)]
    return _ClaimFollowUpResult(
        _claim_response_text(response),
        sources,
        action=intent.action,
        status="calculated",
        item_count=len(payload.items),
        requires_review=response.requires_review,
    )


def _recalculation_context_data(payload: ClaimCalculationRequest, payload_data: dict) -> dict:
    context_data = payload.context.model_dump()
    original_context = payload_data.get("context") or {}
    special_status = original_context.get("special_calculation_status")
    if special_status:
        context_data["special_calculation_status"] = special_status
    return context_data


def _target_not_found_answer(snapshot: dict, target_text: str) -> str:
    names = _snapshot_line_names(snapshot)
    suffix = f" 현재 계산에 저장된 항목은 {', '.join(names[:8])}입니다." if names else ""
    return f"'{target_text}'에 해당하는 계산 항목을 찾지 못했습니다. 항목명을 계산 결과의 항목명과 같게 적어 다시 질문해 주세요.{suffix}"


def _ambiguous_target_answer(matches: list[dict]) -> str:
    names = [str(line.get("input_name") or "항목명 없음") for line in matches[:8]]
    return "요청한 항목명이 여러 항목과 맞습니다. 다음 중 하나의 항목명을 그대로 적어 다시 질문해 주세요: " + ", ".join(names)


def _not_covered_answer_and_source(snapshot: dict, target_line: dict) -> tuple[str, dict]:
    previous = snapshot_payable_amount(snapshot)
    removed = line_payable_amount(target_line)
    updated = previous - removed
    if updated < 0:
        updated = type(previous)("0")
    target_name = str(target_line.get("input_name") or "해당 항목")
    if removed == 0:
        answer = (
            f"{target_name}은 기존 계산에서 예상 지급금액 0원으로 반영되어 있었습니다. "
            f"따라서 보상하지 않는다고 보아도 기존 예상 지급금액 {money_text(previous)}원은 변하지 않습니다."
        )
    else:
        answer = (
            f"{target_name}을 보상하지 않는다고 보면 기존 예상 지급금액 {money_text(previous)}원에서 "
            f"해당 항목 지급액 {money_text(removed)}원을 제외해 예상 지급금액은 {money_text(updated)}원입니다."
        )
    return answer, _claim_follow_up_snapshot_source(snapshot, target_line, updated, answer)


def _claim_follow_up_snapshot_source(
    snapshot: dict,
    target_line: dict,
    updated_payable,
    answer: str,
) -> dict:
    updated_snapshot = deepcopy(snapshot)
    updated_snapshot["schema_version"] = 2
    updated_snapshot["state"] = "conditional"
    updated_snapshot["claim_id"] = str(uuid4())
    updated_snapshot["created_at"] = datetime.now(timezone.utc).isoformat()
    updated_snapshot["follow_up"] = {
        "kind": "conditional_not_covered",
        "target_line_id": target_line.get("line_id"),
        "target_name": target_line.get("input_name"),
        "answer": answer,
    }

    result = updated_snapshot.setdefault("result", {})
    result["payable_amount"] = str(updated_payable)
    result["calculation_status"] = "conditional_follow_up"
    result["requires_review"] = True
    review_reasons = list(result.get("review_reasons") or [])
    target_name = str(target_line.get("input_name") or "해당 항목")
    review_reasons.append(f"후속 질의에서 '{target_name}' 항목을 보상하지 않는 조건으로 가정했습니다.")
    result["review_reasons"] = list(dict.fromkeys(review_reasons))

    for line in result.get("line_results") or []:
        if not isinstance(line, dict):
            continue
        if _same_snapshot_line(line, target_line):
            line["payable_amount"] = "0"
            line["calculation_status"] = "conditional_not_covered"
            line["excluded_from_calculation"] = True
            line["requires_review"] = True
            reasons = list(line.get("review_reasons") or [])
            reasons.append("후속 질의에서 보상하지 않는 조건으로 가정했습니다.")
            line["review_reasons"] = list(dict.fromkeys(reasons))
            break

    return {"__kind": "assistant_meta", "claim_snapshot": updated_snapshot}


def _same_snapshot_line(line: dict, target_line: dict) -> bool:
    line_id = line.get("line_id")
    target_id = target_line.get("line_id")
    if line_id and target_id:
        return line_id == target_id
    return line.get("input_name") == target_line.get("input_name")


def _snapshot_line_names(snapshot: dict) -> list[str]:
    result = snapshot.get("result") or {}
    names = []
    for line in result.get("line_results") or []:
        if isinstance(line, dict) and line.get("input_name"):
            names.append(str(line["input_name"]))
    return list(dict.fromkeys(names))


def _provider_from_model_id(model: str) -> str:
    if ":" in model:
        provider = model.split(":", 1)[0]
        if provider in {"openai", "local", "vllm", "sglang"}:
            return provider
    return "openai" if model.startswith("gpt-") else "vllm"


def _assistant_meta(sources: list[dict] | None) -> dict:
    """Return the private assistant metadata persisted with a response."""

    return assistant_metadata(sources)


def _public_sources(sources: list[dict] | None) -> list[dict]:
    return public_sources(sources)


def _public_graph_payload(graph_payload: dict | None) -> dict | None:
    return public_graph_payload(graph_payload)


def _history_for_conversation(history: list[ChatMessage]) -> list[dict]:
    return [
        {
            "role": message.role,
            "sources": {"assistant_meta": _assistant_meta(message.sources or [])},
        }
        for message in history
    ]


def _current_ontology_manifest_hash() -> str | None:
    report = getattr(get_default_ontology_registry(), "integrity_report", None)
    value = getattr(report, "manifest_content_hash", "")
    return str(value).strip() or None


def _conversation_interaction_payload(state: ConversationState | dict | None) -> dict | None:
    """Expose only the current pending selection contract to the browser."""

    if isinstance(state, dict):
        try:
            state = parse_conversation_state(state)
        except ValueError:
            return None
    if state is None:
        return None
    request = state.clarification_request
    if request is None or request.status != "pending" or not request.slots:
        return None
    return {
        "request_id": request.request_id,
        "slots": [
            {
                "slot_id": slot.slot_id,
                "question": slot.question,
                "allowed_values": list(slot.allowed_values),
            }
            for slot in request.slots
        ],
        "query_scope": {
            "route": request.query_scope.route,
            "policy_generation": request.query_scope.policy_generation,
            "doc_filter": list(request.query_scope.doc_filter),
            "index_mode": request.query_scope.index_mode,
        },
    }


def _existing_turn(history: list[ChatMessage], turn_id: str) -> ChatMessage | None:
    for message in reversed(history):
        if message.role != "assistant":
            continue
        turn = _assistant_meta(message.sources or []).get("turn")
        if isinstance(turn, dict) and turn.get("turn_id") == turn_id:
            return message
    return None


def _persisted_sources(
    sources: list[dict],
    *,
    turn_id: str,
    graph_payload: dict | None,
    warnings: list[dict] | None,
    conversation_state: ConversationState | None,
) -> list[dict]:
    metadata = _assistant_meta(sources)
    metadata["__kind"] = "assistant_meta"
    metadata["turn"] = {"turn_id": turn_id}
    if graph_payload is not None:
        metadata["graph_result"] = graph_payload
    if warnings:
        metadata["warnings"] = list(warnings)
    if conversation_state is not None:
        metadata["conversation_state"] = serialize_conversation_state(conversation_state)
    return storage_sources(sources) + [metadata]


def _ambiguous_continuation_answer(context) -> str:
    request = context.pending_request
    if request is None or not request.slots:
        return "이전 확인 항목에 대한 답인지 새 질문인지 구분하기 어렵습니다. 확인할 조건을 함께 알려주세요."
    slot = request.slots[0]
    return f"이전 확인 항목에 대한 답인지 구분하기 어렵습니다. {slot.question}"


async def _replay_persisted_turn(chat_session: ChatSession, message: ChatMessage, turn_id: str):
    metadata = _assistant_meta(message.sources or [])
    yield _sse("session", {"session_id": chat_session.id, "turn_id": turn_id, "replayed": True})
    yield _sse("status", "replaying")
    public_sources = _public_sources(message.sources or [])
    if public_sources:
        yield _sse("sources", public_sources)
    graph_payload = metadata.get("graph_result")
    if isinstance(graph_payload, dict):
        yield _sse("graph", _public_graph_payload(graph_payload))
    for warning in public_warnings(metadata.get("warnings")):
        if isinstance(warning, dict):
            yield _sse("warning", warning)
    interaction = _conversation_interaction_payload(metadata.get("conversation_state"))
    if interaction is not None:
        yield _sse("conversation", interaction)
    yield _sse("final", {"answer": message.content})
    yield _sse(
        "done",
        {"session_id": chat_session.id, "answer": message.content, "persisted": True, "replayed": True},
    )


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
    turn_id = chat_request.turn_id or f"turn-{uuid4().hex}"

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
        manifest_hash = _current_ontology_manifest_hash()
        conversation_context = resolve_conversation_context(
            chat_request.query,
            _history_for_conversation(history),
            current_manifest_hash=manifest_hash,
            clarification=chat_request.clarification or None,
        )
        selected_policy_generation = (
            chat_request.policy_generation or conversation_context.query_scope.policy_generation
        )
        requested_index_mode, effective_index_mode = _resolve_chat_index_modes(
            _query_with_policy_generation(conversation_context.route_query, selected_policy_generation),
            chat_request.index_mode,
        )
        context_query = _query_with_policy_generation(conversation_context.route_query, selected_policy_generation)
        started = time.perf_counter()
        try:
            existing_turn = _existing_turn(history, turn_id)
            if existing_turn is not None:
                async for event in _replay_persisted_turn(chat_session, existing_turn, turn_id):
                    yield event
                return
            yield _sse("session", {"session_id": chat_session.id, "turn_id": turn_id})
            yield _sse("status", "searching")
            claim_follow_up = None
            if conversation_context.kind in {"new_question", "topic_switch"}:
                claim_follow_up = await _handle_claim_follow_up(
                    chat_session_id=chat_session.id,
                    query=chat_request.query,
                    history=history,
                    selected_model=selected_model,
                    index_mode=effective_index_mode,
                )
            if claim_follow_up is not None:
                try:
                    await _persist_turn(
                        db,
                        chat_session.id,
                        chat_request.query,
                        claim_follow_up.answer,
                        claim_follow_up.sources,
                        turn_id=turn_id,
                        conversation_state=conversation_context.state_after,
                    )
                except Exception:
                    logger.exception("failed to persist claim follow-up session_id=%s", chat_session.id)
                    await db.rollback()
                    yield _sse(
                        "error",
                        {
                            "code": "CHAT_HISTORY_PERSIST_FAILED",
                            "message": "대화 저장 중 오류가 발생했습니다. 같은 대화에서 다시 시도해 주세요.",
                        },
                    )
                    return
                yield _sse("sources", _public_sources(claim_follow_up.sources))
                interaction = _conversation_interaction_payload(conversation_context.state_after)
                if interaction is not None:
                    yield _sse("conversation", interaction)
                yield _sse("final", {"answer": claim_follow_up.answer})
                yield _sse(
                    "done",
                    {"session_id": chat_session.id, "answer": claim_follow_up.answer, "persisted": True},
                )
                await log_audit_event(
                    db,
                    "CHAT_QUERY",
                    user_id=user.username,
                    ip_address=_client_ip(request),
                    detail={
                        "model": selected_model,
                        "mode": chat_request.mode,
                        "resolved_route": "claim_follow_up",
                        "top_k": chat_request.top_k,
                        "temperature": chat_request.temperature,
                        "index_mode": requested_index_mode,
                        "effective_index_mode": effective_index_mode,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                        "session_id": chat_session.id,
                        "source_count": len(claim_follow_up.sources),
                        "claim_follow_up_action": claim_follow_up.action,
                        "claim_follow_up_status": claim_follow_up.status,
                        "claim_follow_up_item_count": claim_follow_up.item_count,
                        "claim_follow_up_requires_review": claim_follow_up.requires_review,
                        "turn_id": turn_id,
                        "conversation_kind": conversation_context.kind,
                        "query_preview": chat_request.query.strip()[:200],
                        "request_id": getattr(getattr(request, "state", None), "request_id", None),
                    },
                )
                return
            if conversation_context.kind == "ambiguous_continuation":
                answer = _ambiguous_continuation_answer(conversation_context)
                try:
                    await _persist_turn(
                        db,
                        chat_session.id,
                        chat_request.query,
                        answer,
                        [],
                        turn_id=turn_id,
                        conversation_state=conversation_context.state_after,
                    )
                except Exception:
                    logger.exception("failed to persist ambiguous continuation session_id=%s", chat_session.id)
                    await db.rollback()
                    yield _sse(
                        "error",
                        {
                            "code": "CHAT_HISTORY_PERSIST_FAILED",
                            "message": "대화 저장 중 오류가 발생했습니다. 같은 대화에서 다시 시도해 주세요.",
                        },
                    )
                    return
                interaction = _conversation_interaction_payload(conversation_context.state_after)
                if interaction is not None:
                    yield _sse("conversation", interaction)
                yield _sse("final", {"answer": answer})
                yield _sse("done", {"session_id": chat_session.id, "answer": answer, "persisted": True})
                return
            system_prompt = SYSTEM_PROMPT
            resolved_mode = chat_request.mode
            effective_filters = dict(chat_request.filters or {})
            resolved_intent = None
            route_reason = "explicit_mode"
            matched_cues: list[str] = []
            if chat_request.mode == "general":
                route = resolve_query_route(conversation_context.route_query, effective_filters)
                resolved_mode = route.route
                effective_filters = route.filters
                resolved_intent = route.intent
                route_reason = route.route_reason
                matched_cues = route.matched_cues
            auto_decision = resolve_auto_rag_params(
                question=conversation_context.route_query,
                mode=resolved_mode,
                filters=effective_filters,
                requested_top_k=chat_request.top_k,
                requested_temperature=chat_request.temperature,
                auto_params=chat_request.auto_params,
                config_mode=config.AUTO_RAG_PARAMS_MODE,
                allow_manual_override=config.AUTO_RAG_ALLOW_MANUAL_OVERRIDE,
                max_temperature=config.AUTO_RAG_MAX_TEMPERATURE,
                top_k_strategy=(
                    TOPK_STRATEGY_RULE
                    if chat_request.adaptive_k is False
                    else config.AUTO_RAG_TOPK_STRATEGY
                ),
                profile_policy_path=config.AUTO_RAG_PROFILE_POLICY_PATH,
                temperature_policy_path=config.AUTO_RAG_TEMPERATURE_POLICY_PATH,
            )
            effective_top_k = auto_decision.effective_top_k
            retrieval_top_k = auto_decision.retrieval_top_k or effective_top_k
            effective_temperature = auto_decision.effective_temperature
            pipeline = _get_pipeline(selected_model, retrieval_top_k, effective_index_mode)
            doc_filter = None
            if resolved_mode == "quickcode":
                chunks, sources, prompt, system_prompt, doc_filter = await prepare_quickcode_context(
                    pipeline,
                    chat_request.query,
                    effective_filters,
                )
            elif resolved_mode == "formal":
                formal_kwargs = {}
                if selected_policy_generation:
                    formal_kwargs["policy_generation"] = selected_policy_generation
                chunks, sources, prompt, doc_filter = await prepare_formal_context(
                    pipeline,
                    context_query,
                    effective_top_k,
                    history,
                    effective_filters,
                    chat_request.memo,
                    **formal_kwargs,
                )
            else:
                retrieval_kwargs = {"auto_params": auto_decision}
                if selected_policy_generation:
                    retrieval_kwargs["policy_generation"] = selected_policy_generation
                retrieval_kwargs["conversation_context"] = conversation_context
                chunks, sources, prompt, graph_payload, warnings, deterministic_answer, debug_info = await prepare_retrieved_context(
                    pipeline,
                    context_query,
                    retrieval_top_k,
                    history,
                    effective_filters,
                    **retrieval_kwargs,
                )
            conversation_scope = ConversationQueryScope(
                route=resolved_mode,
                intent=resolved_intent,
                policy_generation=selected_policy_generation,
                doc_filter=tuple(str(item) for item in (effective_filters.get("doc_filter") or []) if str(item).strip()),
                index_mode=effective_index_mode,
            )
            conversation_state = state_with_pending_clarification(
                conversation_context.state_after,
                topic_anchor=conversation_context.route_query,
                origin_turn_id=turn_id,
                ontology_manifest_hash=manifest_hash or "",
                query_scope=conversation_scope,
                slots=clarification_slots_from_payload(graph_payload),
            )
            prompt = _prompt_with_policy_generation(prompt, selected_policy_generation)
            yield _sse("sources", _public_sources(sources))
            if graph_payload is not None:
                logger.info(
                    "chat graph payload review_paths=%s exclusions=%s",
                    [path.get("path_type") for path in graph_payload.get("graph_review_paths", [])],
                    [path.get("exclusion_reasons") for path in graph_payload.get("graph_review_paths", [])],
                )
                yield _sse("graph", _public_graph_payload(graph_payload))
            for warning in public_warnings(warnings):
                yield _sse("warning", warning)

            if deterministic_answer is not None:
                for token in _chunk_text(deterministic_answer):
                    tokens.append(token)
                    yield _sse("token", {"t": token})
                    await asyncio.sleep(0)
            else:
                # A renderable Graph/canonical panel can replace model templates. Buffer it so
                # no streamed text disappears when the final normalized answer is emitted.
                suppress_live_tokens = graph_payload_has_renderable_evidence(graph_payload)
                llm_stream = _generate_llm_stream(
                    pipeline.llm,
                    prompt,
                    system_prompt,
                    effective_temperature,
                    chat_request.reasoning_mode,
                )
                for token in llm_stream:
                    tokens.append(token)
                    if not suppress_live_tokens:
                        yield _sse("token", {"t": token})
                    await asyncio.sleep(0)
                for warning in _llm_safety_warnings(pipeline.llm):
                    warnings.append(warning)
                    public_warning = public_warnings([warning])
                    if public_warning:
                        yield _sse("warning", public_warning[0])

            raw_answer = "".join(tokens).strip()
            if not raw_answer:
                empty_warning = {
                    "code": "EMPTY_LLM_OUTPUT",
                    "message": "모델 응답 본문이 비어 있어 답변을 생성하지 못했습니다.",
                }
                yield _sse("warning", public_warnings([empty_warning])[0])
                answer = "모델 응답 본문이 비어 있어 답변을 생성하지 못했습니다. 검색 근거를 다시 확인해 주세요."
            else:
                answer = finalize_answer_for_question(chat_request.query, raw_answer, chunks, graph_payload)
            try:
                await _persist_turn(
                    db,
                    chat_session.id,
                    chat_request.query,
                    answer,
                    sources,
                    graph_payload=graph_payload,
                    warnings=warnings,
                    turn_id=turn_id,
                    conversation_state=conversation_state,
                )
            except Exception:
                logger.exception("failed to persist chat session_id=%s", chat_session.id)
                await db.rollback()
                yield _sse(
                    "error",
                    {
                        "code": "CHAT_HISTORY_PERSIST_FAILED",
                        "message": "대화 저장 중 오류가 발생했습니다. 같은 대화에서 다시 시도해 주세요.",
                    },
                )
                return
            interaction = _conversation_interaction_payload(conversation_state)
            if interaction is not None:
                yield _sse("conversation", interaction)
            yield _sse("final", {"answer": answer})
            yield _sse("done", {"session_id": chat_session.id, "answer": answer, "persisted": True})
            await log_audit_event(
                db,
                "CHAT_QUERY",
                user_id=user.username,
                ip_address=_client_ip(request),
                detail={
                    "model": selected_model,
                    "mode": chat_request.mode,
                    "resolved_route": resolved_mode,
                    "resolved_intent": resolved_intent,
                    "route_reason": route_reason,
                    "matched_cues": matched_cues,
                    "search_type": (
                        effective_filters.get("search_type")
                        if resolved_mode == "formal"
                        else None
                    ),
                    "top_k": effective_top_k,
                    "retrieval_top_k": retrieval_top_k,
                    "final_top_k": len(chunks) if resolved_mode == "general" and chunks else effective_top_k,
                    "temperature": effective_temperature,
                    "requested_top_k": chat_request.top_k,
                    "requested_temperature": chat_request.temperature,
                    "auto_params": auto_decision.to_payload(),
                    "adaptive_k": chat_request.adaptive_k,
                    "reasoning_mode": chat_request.reasoning_mode,
                    "reasoning_supported": bool(getattr(pipeline.llm, "last_reasoning_supported", False)),
                    "reasoning_filtered": bool(getattr(pipeline.llm, "last_reasoning_filtered", False)),
                    "finish_reason": getattr(pipeline.llm, "last_finish_reason", None),
                    "final_retry_finish_reason": getattr(pipeline.llm, "last_final_retry_finish_reason", None),
                    "warning_codes": [warning.get("code") for warning in warnings if warning.get("code")],
                    "index_mode": requested_index_mode,
                    "effective_index_mode": effective_index_mode,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    "policy_generation": selected_policy_generation,
                    "session_id": chat_session.id,
                    "turn_id": turn_id,
                    "conversation_kind": conversation_context.kind,
                    "source_count": len(sources),
                    "query_preview": chat_request.query.strip()[:200],
                    "doc_filter": doc_filter,
                    "rag_diagnostics": _build_rag_diagnostics(
                        question=chat_request.query,
                        model=selected_model,
                        index_mode=requested_index_mode,
                        effective_index_mode=effective_index_mode,
                        auto_params=auto_decision,
                        debug=debug_info,
                        source_count=len(sources),
                        warnings=warnings,
                        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
                    ) if resolved_mode == "general" else None,
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
    return f"sglang:{config.SGLANG_DEFAULT_MODEL}"


def _resolve_chat_index_modes(question: str, requested_index_mode: str) -> tuple[str, str]:
    """Resolve chat index modes without allowing OCR-backed data to be skipped."""

    requested = (requested_index_mode or "v2_only").strip().lower()
    if requested not in {"default", "v2_only", "v1_v2_combined"}:
        requested = "v2_only"
    effective = resolve_effective_index_mode(question, requested)
    if effective == "default":
        effective = "v2_only"
    return requested, effective


def _get_pipeline(model: str, top_k: int, index_mode: str):
    if index_mode == "default":
        return get_rag_pipeline(model, top_k)
    return get_rag_pipeline(model, top_k, index_mode)


def _policy_generation_label(policy_generation: str | None) -> str | None:
    if policy_generation == "5th":
        return "5세대"
    if policy_generation == "4th":
        return "4세대"
    return None


def _query_with_policy_generation(query: str, policy_generation: str | None) -> str:
    label = _policy_generation_label(policy_generation)
    return f"[선택된 실손 세대 기준: {label} 실손]\n{query}" if label else query


def _prompt_with_policy_generation(prompt: str, policy_generation: str | None) -> str:
    label = _policy_generation_label(policy_generation)
    if not label:
        return prompt
    return f"[답변 기준]\n사용자가 선택한 실손 세대는 {label} 실손입니다. 세대별 기준이 다른 내용은 이 선택을 우선 적용하고, 답변에 해당 세대 기준임을 명시하세요.\n\n{prompt}"


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
    auto_params: AutoRagParams | None = None,
) -> dict:
    dense_hits = list(getattr(debug, "dense_hits", []) or [])
    bm25_hits = list(getattr(debug, "bm25_hits", []) or [])
    rrf_hits = list(getattr(debug, "rrf_hits", []) or [])
    final_hits = list(getattr(debug, "final_hits", []) or [])
    reranker_scores = list(getattr(debug, "reranker_scores", []) or [])
    auto_cutoff = getattr(debug, "auto_cutoff", None) if debug is not None else None
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
        "auto_params": auto_params.to_payload() if auto_params else None,
        "warnings": warnings,
        "normalized_terms": dict(getattr(graph_plan, "normalized_terms", {}) or {}),
        "term_correction_candidates": list(getattr(graph_plan, "term_correction_candidates", []) or []),
        "ambiguous_terms": list(getattr(graph_plan, "ambiguous_terms", []) or []),
        "clarification_questions": list(getattr(graph_plan, "clarification_questions", []) or []),
        "search_intent": search_intent_payload,
        "retrieval_execution": retrieval_execution_payload,
        "reranker_scores": [_stage_hit_payload(hit) for hit in reranker_scores],
        "auto_cutoff": auto_cutoff.to_payload() if hasattr(auto_cutoff, "to_payload") else None,
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
            _build_hit_step("reranker", "Reranker 점수", reranker_scores),
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


def _stage_hit_payload(hit) -> dict:
    return {
        "chunk_id": getattr(hit, "chunk_id", ""),
        "doc_short": getattr(hit, "doc_short", ""),
        "score": getattr(hit, "score", None),
        "rank": getattr(hit, "rank", None),
        "page_start": getattr(hit, "page_start", None),
        "page_end": getattr(hit, "page_end", None),
        "text_preview": getattr(hit, "text_preview", ""),
    }


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
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    )
    return list(result.scalars())


async def _persist_turn(
    db: AsyncSession,
    session_id: str,
    query: str,
    answer: str,
    sources: list[dict],
    *,
    turn_id: str | None = None,
    graph_payload: dict | None = None,
    warnings: list[dict] | None = None,
    conversation_state: ConversationState | None = None,
) -> None:
    persisted_turn_id = turn_id or f"turn-{uuid4().hex}"
    user_message = ChatMessage(session_id=session_id, role="user", content=query, sources=None)
    db.add(user_message)
    await db.flush()
    resolved_state = (
        finalize_assertion_source(conversation_state, source_message_id=str(user_message.id))
        if conversation_state is not None
        else None
    )
    persisted_sources = _persisted_sources(
        sources,
        turn_id=persisted_turn_id,
        graph_payload=graph_payload,
        warnings=warnings,
        conversation_state=resolved_state,
    )
    db.add(ChatMessage(session_id=session_id, role="assistant", content=answer, sources=persisted_sources))
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
