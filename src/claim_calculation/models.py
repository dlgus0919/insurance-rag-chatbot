"""보험금 계산 파이프라인 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClaimItemInput:
    """사용자가 청구한 개별 항목 입력."""

    line_id: str
    input_name: str
    input_code: str = ""
    claimed_amount: str = "0"
    quantity: str = "1"
    user_category_hint: str = ""  # 예: "급여", "비급여", "3대비급여", "모름"
    is_prescription: bool = False


@dataclass
class ClaimCaseContext:
    """보상 청구 건의 상황 정보."""

    treatment_date: str = ""
    visit_type: str = ""  # 입원: "hospitalization", 통원: "outpatient"
    coverage_topic: str = ""  # "실손", "3대비급여" 등
    diagnosis_code: str = ""  # 진단코드
    diagnosis_name: str = ""  # 진단명
    accident_type: str = ""  # 사고: "accident", 질병: "disease", 상해: "injury"
    situation_note: str = ""  # 상황 메모
    policy_generation: str = "4th"  # "4th" 또는 "5th"
    complication_asserted: bool = False
    same_disease_claimed: bool = False
    same_treatment_purpose_claimed: bool = False
    recurrent_or_continuing_treatment: bool = False
    newly_found_disease_claimed: bool = False
    treatment_purpose: str = ""
    evidence_tags: list[str] = field(default_factory=list)
    facility_type: str = ""
    facility_grade: str = ""


@dataclass
class StandardMatch:
    """비급여 표준모델 데이터베이스 매칭 결과."""

    std_cd: str = ""
    std_cd_nm: str = ""
    mid_category_cd_nm: str = ""
    ins_care_type_cd_nm: str = ""
    medical_class_cd_nm: str = ""
    item_class_level1cd_nm: str = ""
    item_class_level2cd_nm: str = ""
    pay_opn_cd_nm: str = ""
    notes: str = ""
    match_confidence: str = "none"  # "exact", "high", "low", "none"
    requires_user_disambiguation: bool = False
    requires_review: bool = False  # pay_opn_cd_nm이 추가확인이거나 비어있는 경우


@dataclass
class BasisSelection:
    """RAG 검색을 위해 선택된 근거 문서 정보."""

    doc_filter: list[str] = field(default_factory=list)
    selection_reason: str = ""


@dataclass
class CalculationPlan:
    """LLM이 수립한 보상 계산 계획."""

    decision: str = "calculable"  # "calculable", "needs_more_info", "not_covered"
    basis_summary: list[dict[str, str]] = field(default_factory=list)
    variables: dict[str, str | None] = field(default_factory=dict)
    calculation_steps: list[str] = field(default_factory=list)
    formula_intent: str = ""
    uncertainties: list[str] = field(default_factory=list)


@dataclass
class CalculationResult:
    """최종 보험금 계산 결과."""

    claimed_amount: str = "0"
    payable_amount: str = "0"
    deductible: str = "0"
    formula_intent: str = ""
    executed_code: str = ""
    applied_basis: list[dict[str, str]] = field(default_factory=list)
    requires_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    notes: str = ""
    candidates: list[dict[str, str]] = field(default_factory=list)
    policy_generation: str = "4th"
    line_results: list[dict[str, str | bool | list[str]]] = field(default_factory=list)
    applied_limits: dict[str, str] = field(default_factory=dict)
    calculation_status: str = "auto_calculated"
    missing_evidence: list[str] = field(default_factory=list)
    review_actions: list[str] = field(default_factory=list)
    exclusion_reasons: list[str] = field(default_factory=list)
    benefit_limits: list[str] = field(default_factory=list)
    deductible_rules: list[str] = field(default_factory=list)
    required_documents: list[str] = field(default_factory=list)
    coordination_rules: list[str] = field(default_factory=list)
    generation_rules: list[str] = field(default_factory=list)
    graph_review_paths: list[dict[str, Any]] = field(default_factory=list)
    session_assertions: list[dict[str, Any]] = field(default_factory=list)


from decimal import Decimal, InvalidOperation

def parse_money(val: Any) -> Decimal:
    """금액 문자열/숫자를 Decimal로 안전하게 파싱한다.

    예: "150,000" -> 150000
    "150000원" -> 150000
    음수, 0원, 비정상 문자열은 ValueError를 던진다.
    """
    if val is None:
        raise ValueError("금액이 입력되지 않았습니다.")

    if isinstance(val, (int, float, Decimal)):
        d = Decimal(str(val))
    else:
        s = str(val).strip()
        s = s.replace("원", "").replace(",", "").replace(" ", "").strip()
        try:
            d = Decimal(s)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"올바른 금액 형식이 아닙니다: {val}") from exc

    if d <= 0:
        raise ValueError(f"금액은 0보다 큰 양수여야 합니다: {val}")
    return d


def parse_quantity(val: Any) -> Decimal:
    """수량/횟수를 Decimal로 파싱한다.

    음수, 0회, 비정상 문자열은 ValueError를 던진다.
    """
    if val is None:
        raise ValueError("수량이 입력되지 않았습니다.")

    if isinstance(val, (int, float, Decimal)):
        d = Decimal(str(val))
    else:
        s = str(val).strip()
        s = s.replace("회", "").replace("개", "").replace(",", "").replace(" ", "").strip()
        try:
            d = Decimal(s)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"올바른 수량 형식이 아닙니다: {val}") from exc

    if d <= 0:
        raise ValueError(f"수량은 0보다 큰 양수여야 합니다: {val}")
    return d
