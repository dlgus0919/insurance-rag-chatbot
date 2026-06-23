"""Claim calculation API route."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import config
from src.api.db import get_db
from src.api.deps import log_audit_event, require_permission
from src.api.exceptions import ValidationException
from src.api.models import ChatMessage, ChatSession
from src.api.rag_service import get_rag_pipeline
from src.api.schemas.claim import ClaimCalculationRequest, ClaimCalculationResponse
from src.auth.users import User
from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput
from src.claim_calculation.pipeline import run_claim_calculation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/claim", tags=["claim"])
CLAIM_RAG_TOP_K = config.CLAIM_RAG_TOP_K

MODEL_ALIAS = {
    "gemma4": "vllm:gemma-4-26b-a4b-nvfp4",
    "nemotron": "vllm:nemotron-3-nano-30b-a3b-nvfp4",
    "gpt-oss": "sglang:gpt-oss-20b",
    "qwen3": "sglang:qwen3-30b-a3b-instruct-2507-fp8",
}


@router.post("/calculate", response_model=ClaimCalculationResponse)
async def calculate_claim(
    payload: ClaimCalculationRequest,
    request: Request = None,
    user: User = Depends(require_permission("chat.stream")),
    db: AsyncSession | None = Depends(get_db),
) -> ClaimCalculationResponse:
    """Run the latest claim calculation pipeline behind the SPA form."""

    started = time.perf_counter()
    selected_model = _select_model(payload)
    index_mode = _resolve_claim_index_mode(payload.index_mode)
    warnings: list[str] = []
    try:
        pipeline = get_rag_pipeline(selected_model, CLAIM_RAG_TOP_K, index_mode)
    except Exception as exc:
        pipeline = None
        warnings.append("RAG 근거 초기화에 실패하여 구조화 계산만 수행했습니다.")
        logger.warning("Claim calculation RAG initialization failed: %s", exc)

    items = [
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
    ]
    context = ClaimCaseContext(**payload.context.model_dump())

    try:
        result = run_claim_calculation(
            rag_pipeline=pipeline,
            items=items,
            context=context,
            basis_mode=payload.basis_mode,
            selected_basis_docs=payload.selected_basis_docs,
            use_fake_planner=payload.use_fake_planner,
            model_id=selected_model.split(":", 1)[1] if ":" in selected_model else selected_model,
            provider=_provider_from_model(selected_model, payload.provider),
        )
    except ValueError as exc:
        raise ValidationException(detail=str(exc)) from exc

    response = ClaimCalculationResponse.from_result(result, warnings)
    if db is not None and payload.save_to_history:
        chat_session = await _ensure_claim_session(db, user.username, payload.session_id, _claim_title(items))
        response.session_id = chat_session.id
        await _persist_claim_turn(db, chat_session.id, payload, response)

    if db is not None:
        await log_audit_event(
            db,
            "CLAIM_CALCULATION",
            user_id=user.username,
            ip_address=request.client.host if request and request.client else None,
            detail={
                "model": selected_model,
                "index_mode": index_mode,
                "requested_index_mode": payload.index_mode,
                "item_count": len(items),
                "requires_review": response.requires_review,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "request_id": getattr(getattr(request, "state", None), "request_id", None),
            },
        )
    return response


async def _ensure_claim_session(
    db: AsyncSession,
    username: str,
    session_id: str | None,
    title: str,
) -> ChatSession:
    if session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == username)
        )
        chat_session = result.scalar_one_or_none()
        if chat_session is not None:
            return chat_session

    chat_session = ChatSession(user_id=username, title=title[:40] or "보험금 계산")
    db.add(chat_session)
    await db.commit()
    await db.refresh(chat_session)
    return chat_session


async def _persist_claim_turn(
    db: AsyncSession,
    session_id: str,
    payload: ClaimCalculationRequest,
    response: ClaimCalculationResponse,
) -> None:
    db.add_all(
        [
            ChatMessage(session_id=session_id, role="user", content=_claim_user_text(payload), sources=None),
            ChatMessage(
                session_id=session_id,
                role="assistant",
                content=_claim_response_text(response),
                sources=response.applied_basis or None,
            ),
        ]
    )
    await db.commit()


def _claim_title(items: list[ClaimItemInput]) -> str:
    first = items[0].input_name if items else ""
    suffix = f" 외 {len(items) - 1}건" if len(items) > 1 else ""
    return f"보험금 계산: {first}{suffix}"


def _claim_user_text(payload: ClaimCalculationRequest) -> str:
    generation = "5세대" if payload.context.policy_generation == "5th" else "4세대"
    lines = []
    for item in payload.items:
        insured = item.insured_copay_amount or "0"
        nonpay = item.nonpay_amount or "0"
        lines.append(f"{item.input_name} 급여본인부담 {insured}원 / 비급여 {nonpay}원 x {item.quantity}")
    return f"[보험금 계산/{generation}] " + ", ".join(lines)


def _claim_response_text(response: ClaimCalculationResponse) -> str:
    status = "검토 필요" if response.requires_review else "계산 완료"
    return "\n".join(
        [
            f"보험금 계산 결과: {status}",
            f"- 총 청구금액: {response.claimed_amount}원",
            f"- 예상 공제금액: {response.deductible}원",
            f"- 예상 지급금액: {response.payable_amount}원",
            f"- 메모: {response.notes}",
        ]
    )


def _select_model(payload: ClaimCalculationRequest) -> str:
    if payload.model:
        return MODEL_ALIAS.get(payload.model, payload.model)
    if payload.provider == "openai":
        return config.OPENAI_DEFAULT_MODEL
    return f"sglang:{config.SGLANG_DEFAULT_MODEL}"


def _resolve_claim_index_mode(index_mode: str) -> str:
    normalized = (index_mode or "v2_only").strip().lower()
    if normalized == "default":
        return "v2_only"
    if normalized in {"v2_only", "v1_v2_combined"}:
        return normalized
    return "v2_only"


def _provider_from_model(model: str, requested_provider: str | None) -> str:
    if requested_provider in {"vllm", "sglang", "openai"}:
        return requested_provider
    if ":" in model:
        return model.split(":", 1)[0]
    return "openai" if model.startswith("gpt-") else "vllm"
