"""Claim calculation request and response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.claim_calculation.models import CalculationResult


class ClaimItemRequest(BaseModel):
    """One claim line item entered by the user."""

    line_id: str | None = None
    input_name: str = Field(..., min_length=1)
    input_code: str = ""
    claimed_amount: str = Field(..., min_length=1)
    quantity: str = "1"
    user_category_hint: str = ""
    is_prescription: bool = False


class ClaimCaseContextRequest(BaseModel):
    """Claim-level context for payout calculation."""

    treatment_date: str = ""
    visit_type: Literal["", "hospitalization", "outpatient"] = ""
    coverage_topic: str = ""
    diagnosis_code: str = ""
    diagnosis_name: str = ""
    accident_type: str = ""
    situation_note: str = ""
    policy_generation: Literal["4th", "5th"] = "4th"
    facility_grade: Literal["", "clinic", "hospital", "general_hospital", "tertiary_hospital"] = ""


class ClaimCalculationRequest(BaseModel):
    """Claim calculation payload."""

    items: list[ClaimItemRequest] = Field(..., min_length=1)
    context: ClaimCaseContextRequest = Field(default_factory=ClaimCaseContextRequest)
    basis_mode: Literal["auto", "manual"] = "auto"
    selected_basis_docs: list[str] | None = None
    use_fake_planner: bool = True
    model: str | None = None
    provider: Literal["openai", "local", "vllm", "sglang"] | None = None
    top_k: int = Field(default=6, ge=1, le=20)
    index_mode: Literal["default", "v2_only", "v1_v2_combined"] = "default"


class ClaimCalculationResponse(BaseModel):
    """JSON-safe calculation result returned to the SPA."""

    claimed_amount: str
    payable_amount: str
    deductible: str
    formula_intent: str
    executed_code: str
    applied_basis: list[dict[str, str]]
    requires_review: bool
    review_reasons: list[str]
    notes: str
    candidates: list[dict[str, str]]
    policy_generation: str = "4th"
    line_results: list[dict] = Field(default_factory=list)
    applied_limits: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_result(cls, result: CalculationResult, warnings: list[str] | None = None) -> "ClaimCalculationResponse":
        return cls(
            claimed_amount=result.claimed_amount,
            payable_amount=result.payable_amount,
            deductible=result.deductible,
            formula_intent=result.formula_intent,
            executed_code=result.executed_code,
            applied_basis=result.applied_basis,
            requires_review=result.requires_review,
            review_reasons=result.review_reasons,
            notes=result.notes,
            candidates=result.candidates,
            policy_generation=result.policy_generation,
            line_results=result.line_results,
            applied_limits=result.applied_limits,
            warnings=warnings or [],
        )
