"""Claim calculation API route."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src import config
from src.api.db import get_db
from src.api.deps import log_audit_event, require_permission
from src.api.exceptions import ValidationException
from src.api.rag_service import get_rag_pipeline
from src.api.schemas.claim import ClaimCalculationRequest, ClaimCalculationResponse
from src.auth.users import User
from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput
from src.claim_calculation.pipeline import run_claim_calculation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/claim", tags=["claim"])

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
    warnings: list[str] = []
    try:
        pipeline = get_rag_pipeline(selected_model, payload.top_k, payload.index_mode)
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
            quantity=item.quantity,
            user_category_hint=item.user_category_hint,
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
    if db is not None:
        await log_audit_event(
            db,
            "CLAIM_CALCULATION",
            user_id=user.username,
            ip_address=request.client.host if request and request.client else None,
            detail={
                "model": selected_model,
                "index_mode": payload.index_mode,
                "item_count": len(items),
                "requires_review": response.requires_review,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "request_id": getattr(getattr(request, "state", None), "request_id", None),
            },
        )
    return response


def _select_model(payload: ClaimCalculationRequest) -> str:
    if payload.model:
        return MODEL_ALIAS.get(payload.model, payload.model)
    if payload.provider == "openai":
        return config.OPENAI_DEFAULT_MODEL
    return f"vllm:{config.VLLM_DEFAULT_MODEL}"


def _provider_from_model(model: str, requested_provider: str | None) -> str:
    if requested_provider in {"vllm", "sglang", "openai"}:
        return requested_provider
    if ":" in model:
        return model.split(":", 1)[0]
    return "openai" if model.startswith("gpt-") else "vllm"
