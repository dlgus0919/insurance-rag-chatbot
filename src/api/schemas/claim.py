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
    claimed_amount: str = ""
    insured_copay_amount: str = ""
    nonpay_amount: str = ""
    quantity: str = "1"
    user_category_hint: str = ""
    extra_info: str = ""


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
    complication_asserted: bool = False
    same_disease_claimed: bool = False
    same_treatment_purpose_claimed: bool = False
    recurrent_or_continuing_treatment: bool = False
    newly_found_disease_claimed: bool = False
    treatment_purpose: str = ""
    evidence_tags: list[str] = Field(default_factory=list)
    facility_type: str = ""
    facility_grade: str = ""


class ClaimCalculationRequest(BaseModel):
    """Claim calculation payload."""

    session_id: str | None = None
    save_to_history: bool = True
    items: list[ClaimItemRequest] = Field(..., min_length=1)
    context: ClaimCaseContextRequest = Field(default_factory=ClaimCaseContextRequest)
    basis_mode: Literal["auto", "manual"] = "auto"
    selected_basis_docs: list[str] | None = None
    use_fake_planner: bool = True
    model: str | None = None
    provider: Literal["openai", "local", "vllm", "sglang"] | None = None
    top_k: int = Field(default=6, ge=1, le=20)
    index_mode: Literal["default", "v2_only", "v1_v2_combined"] = "v2_only"


class ClaimCalculationResponse(BaseModel):
    """JSON-safe calculation result returned to the SPA."""

    session_id: str | None = None
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
    calculation_status: str = "auto_calculated"
    missing_evidence: list[str] = Field(default_factory=list)
    review_actions: list[str] = Field(default_factory=list)
    exclusion_reasons: list[str] = Field(default_factory=list)
    benefit_limits: list[str] = Field(default_factory=list)
    deductible_rules: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    coordination_rules: list[str] = Field(default_factory=list)
    generation_rules: list[str] = Field(default_factory=list)
    graph_review_paths: list[dict] = Field(default_factory=list)
    session_assertions: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_result(
        cls,
        result: CalculationResult,
        warnings: list[str] | None = None,
        session_id: str | None = None,
    ) -> "ClaimCalculationResponse":
        return cls(
            session_id=session_id,
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
            calculation_status=result.calculation_status,
            missing_evidence=result.missing_evidence,
            review_actions=result.review_actions,
            exclusion_reasons=result.exclusion_reasons,
            benefit_limits=result.benefit_limits,
            deductible_rules=result.deductible_rules,
            required_documents=result.required_documents,
            coordination_rules=result.coordination_rules,
            generation_rules=result.generation_rules,
            graph_review_paths=result.graph_review_paths,
            session_assertions=result.session_assertions,
            warnings=warnings or [],
        )
