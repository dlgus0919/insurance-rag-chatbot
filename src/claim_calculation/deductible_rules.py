"""4/5세대 실손보험 공제 규칙 테이블.

하드코딩된 공제율 분기를 구조화된 데이터 테이블로 분리한다.
약관 원문 근거:
- 4세대: 실손의료비 표준약관 (금융위원회 2017)
- 5세대: (별첨3)[별표 15] 표준약관(제5-13조제1항관련) (6).pdf
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


# 의료기관 등급 상수
FACILITY_CLINIC = "clinic"              # 의원
FACILITY_HOSPITAL = "hospital"          # 병원
FACILITY_GENERAL = "general_hospital"   # 종합병원
FACILITY_TERTIARY = "tertiary_hospital" # 상급종합병원

FACILITY_GRADES = (FACILITY_CLINIC, FACILITY_HOSPITAL, FACILITY_GENERAL, FACILITY_TERTIARY)
DEFAULT_FACILITY = FACILITY_CLINIC


@dataclass(frozen=True)
class DeductibleRule:
    """하나의 공제 규칙 행."""

    generation: str
    category: str
    visit_type: str          # "hospitalization" | "outpatient"
    copay_ratio: Decimal
    min_deductible: dict[str, Decimal]   # 의료기관 등급 -> 최소공제금액
    per_visit_limit: Decimal | None = None
    annual_limit: Decimal | None = None
    annual_visit_limit: int | None = None
    description: str = ""

    def get_min_deductible(self, facility_grade: str = "") -> Decimal:
        """의료기관 등급에 해당하는 최소공제금액을 반환한다."""
        grade = facility_grade if facility_grade in self.min_deductible else DEFAULT_FACILITY
        return self.min_deductible.get(grade, Decimal("0"))


@dataclass(frozen=True)
class PrescriptionRule:
    """처방약(약제비) 전용 공제 규칙."""

    generation: str
    deductible_amount: Decimal           # 고정 공제금액
    per_visit_limit: Decimal | None = None
    description: str = ""


# ---------------------------------------------------------------------------
# 4세대 규칙 테이블
# ---------------------------------------------------------------------------

_NO_MIN = {g: Decimal("0") for g in FACILITY_GRADES}

_4TH_OUTPATIENT_BENEFIT_MIN = {
    FACILITY_CLINIC: Decimal("10000"),
    FACILITY_HOSPITAL: Decimal("15000"),
    FACILITY_GENERAL: Decimal("20000"),
    FACILITY_TERTIARY: Decimal("20000"),
}

_4TH_OUTPATIENT_NON_BENEFIT_MIN = {
    FACILITY_CLINIC: Decimal("30000"),
    FACILITY_HOSPITAL: Decimal("30000"),
    FACILITY_GENERAL: Decimal("30000"),
    FACILITY_TERTIARY: Decimal("30000"),
}

_4TH_RULES: list[DeductibleRule] = [
    # 급여 입원
    DeductibleRule(
        generation="4th", category="급여", visit_type="hospitalization",
        copay_ratio=Decimal("0.2"), min_deductible=_NO_MIN,
        annual_limit=Decimal("50000000"),
        description="4세대 급여 입원: 본인부담금 20%, 연간 5천만원 한도",
    ),
    # 급여 통원
    DeductibleRule(
        generation="4th", category="급여", visit_type="outpatient",
        copay_ratio=Decimal("0.2"), min_deductible=_4TH_OUTPATIENT_BENEFIT_MIN,
        per_visit_limit=Decimal("250000"), annual_visit_limit=180,
        description="4세대 급여 통원: 20% 및 의료기관별 최소공제, 건당 25만원, 연 180건",
    ),
    # 비급여/3대비급여/중증/비중증 입원 (4세대는 모두 동일 30%)
    DeductibleRule(
        generation="4th", category="비급여", visit_type="hospitalization",
        copay_ratio=Decimal("0.3"), min_deductible=_NO_MIN,
        annual_limit=Decimal("50000000"),
        description="4세대 비급여 입원: 30% 공제, 연간 5천만원 한도",
    ),
    # 비급여 통원
    DeductibleRule(
        generation="4th", category="비급여", visit_type="outpatient",
        copay_ratio=Decimal("0.3"), min_deductible=_4TH_OUTPATIENT_NON_BENEFIT_MIN,
        per_visit_limit=Decimal("250000"), annual_visit_limit=180,
        description="4세대 비급여 통원: 30% 및 최소공제 3만원, 건당 25만원, 연 180건",
    ),
]

# 4세대 처방약
_4TH_PRESCRIPTION = PrescriptionRule(
    generation="4th",
    deductible_amount=Decimal("8000"),
    per_visit_limit=Decimal("50000"),
    description="4세대 처방약: 건당 8천원 공제, 건당 5만원 한도",
)


# ---------------------------------------------------------------------------
# 5세대 규칙 테이블
# ---------------------------------------------------------------------------

_5TH_OUTPATIENT_BENEFIT_MIN = {
    FACILITY_CLINIC: Decimal("10000"),
    FACILITY_HOSPITAL: Decimal("15000"),
    FACILITY_GENERAL: Decimal("20000"),
    FACILITY_TERTIARY: Decimal("20000"),
}

_5TH_OUTPATIENT_SERIOUS_MIN = {
    FACILITY_CLINIC: Decimal("30000"),
    FACILITY_HOSPITAL: Decimal("30000"),
    FACILITY_GENERAL: Decimal("30000"),
    FACILITY_TERTIARY: Decimal("30000"),
}

_5TH_OUTPATIENT_NON_SERIOUS_MIN = {
    FACILITY_CLINIC: Decimal("50000"),
    FACILITY_HOSPITAL: Decimal("50000"),
    FACILITY_GENERAL: Decimal("50000"),
    FACILITY_TERTIARY: Decimal("50000"),
}

_5TH_RULES: list[DeductibleRule] = [
    # 급여 입원
    DeductibleRule(
        generation="5th", category="급여", visit_type="hospitalization",
        copay_ratio=Decimal("0.2"), min_deductible=_NO_MIN,
        annual_limit=Decimal("50000000"),
        description="5세대 급여 입원: 본인부담금 20%, 연간 5천만원 한도",
    ),
    # 급여 통원
    DeductibleRule(
        generation="5th", category="급여", visit_type="outpatient",
        copay_ratio=Decimal("0.2"), min_deductible=_5TH_OUTPATIENT_BENEFIT_MIN,
        per_visit_limit=Decimal("200000"),
        description="5세대 급여 통원: 20% 및 의료기관별 최소공제, 건당 20만원",
    ),
    # 중증비급여 입원
    DeductibleRule(
        generation="5th", category="중증비급여", visit_type="hospitalization",
        copay_ratio=Decimal("0.3"), min_deductible=_NO_MIN,
        annual_limit=Decimal("50000000"),
        description="5세대 중증 비급여 입원: 30%, 연간 5천만원 한도",
    ),
    # 중증비급여 통원
    DeductibleRule(
        generation="5th", category="중증비급여", visit_type="outpatient",
        copay_ratio=Decimal("0.3"), min_deductible=_5TH_OUTPATIENT_SERIOUS_MIN,
        per_visit_limit=Decimal("200000"),
        description="5세대 중증 비급여 통원: 30% 및 최소공제 3만원, 건당 20만원",
    ),
    # 3대비급여 입원
    DeductibleRule(
        generation="5th", category="3대비급여", visit_type="hospitalization",
        copay_ratio=Decimal("0.5"), min_deductible=_NO_MIN,
        annual_limit=Decimal("50000000"),
        description="5세대 3대비급여 입원: 50%, 연간 5천만원 한도",
    ),
    # 3대비급여 통원
    DeductibleRule(
        generation="5th", category="3대비급여", visit_type="outpatient",
        copay_ratio=Decimal("0.5"), min_deductible=_5TH_OUTPATIENT_NON_SERIOUS_MIN,
        per_visit_limit=Decimal("200000"),
        description="5세대 3대비급여 통원: 50% 및 최소공제 5만원, 건당 20만원",
    ),
    # 비중증비급여 입원
    DeductibleRule(
        generation="5th", category="비중증비급여", visit_type="hospitalization",
        copay_ratio=Decimal("0.5"), min_deductible=_NO_MIN,
        annual_limit=Decimal("50000000"),
        description="5세대 비중증 비급여 입원: 50%, 연간 5천만원 한도",
    ),
    # 비중증비급여 통원
    DeductibleRule(
        generation="5th", category="비중증비급여", visit_type="outpatient",
        copay_ratio=Decimal("0.5"), min_deductible=_5TH_OUTPATIENT_NON_SERIOUS_MIN,
        per_visit_limit=Decimal("200000"),
        description="5세대 비중증 비급여 통원: 50% 및 최소공제 5만원, 건당 20만원",
    ),
    # 비급여(미분류) 입원
    DeductibleRule(
        generation="5th", category="비급여", visit_type="hospitalization",
        copay_ratio=Decimal("0.5"), min_deductible=_NO_MIN,
        annual_limit=Decimal("50000000"),
        description="5세대 비급여(미분류) 입원: 비중증 기준 임시 50%",
    ),
    # 비급여(미분류) 통원
    DeductibleRule(
        generation="5th", category="비급여", visit_type="outpatient",
        copay_ratio=Decimal("0.5"), min_deductible=_5TH_OUTPATIENT_NON_SERIOUS_MIN,
        per_visit_limit=Decimal("200000"),
        description="5세대 비급여(미분류) 통원: 비중증 기준 임시 50%",
    ),
]

# 5세대 처방약
_5TH_PRESCRIPTION = PrescriptionRule(
    generation="5th",
    deductible_amount=Decimal("8000"),
    per_visit_limit=Decimal("50000"),
    description="5세대 처방약: 건당 8천원 공제, 건당 5만원 한도",
)


# ---------------------------------------------------------------------------
# 인덱스 구성 (lookup 성능)
# ---------------------------------------------------------------------------

def _build_index(rules: list[DeductibleRule]) -> dict[tuple[str, str, str], DeductibleRule]:
    return {(r.generation, r.category, r.visit_type): r for r in rules}


_RULE_INDEX: dict[tuple[str, str, str], DeductibleRule] = {
    **_build_index(_4TH_RULES),
    **_build_index(_5TH_RULES),
}

_PRESCRIPTION_INDEX: dict[str, PrescriptionRule] = {
    "4th": _4TH_PRESCRIPTION,
    "5th": _5TH_PRESCRIPTION,
}

# 4세대 비급여 카테고리 통합 매핑 (4세대는 3대비급여, 중증, 비중증 모두 동일 30%)
_4TH_NON_BENEFIT_ALIASES = {"3대비급여", "중증비급여", "비중증비급여"}


def lookup_rule(
    generation: str,
    category: str,
    visit_type: str,
    facility_grade: str = "",
) -> DeductibleRule:
    """세대, 카테고리, 방문형태에 해당하는 공제 규칙을 반환한다.

    4세대의 경우 3대비급여, 중증비급여, 비중증비급여 모두 "비급여"와 동일 규칙.
    미지원 조합은 해당 세대의 미분류 기본 규칙을 반환한다.
    """
    gen = generation if generation in {"4th", "5th"} else "4th"
    vt = visit_type if visit_type in {"hospitalization", "outpatient"} else "outpatient"

    # 직접 매칭
    key = (gen, category, vt)
    rule = _RULE_INDEX.get(key)
    if rule:
        return rule

    # 4세대 비급여 alias 매핑
    if gen == "4th" and category in _4TH_NON_BENEFIT_ALIASES:
        fallback_key = (gen, "비급여", vt)
        rule = _RULE_INDEX.get(fallback_key)
        if rule:
            return rule

    # 미분류 fallback: 해당 세대의 급여 규칙을 기본으로 반환
    fallback_key = (gen, "급여", vt)
    rule = _RULE_INDEX.get(fallback_key)
    if rule:
        return rule

    # 최종 fallback (도달하지 않아야 함)
    return DeductibleRule(
        generation=gen, category=category, visit_type=vt,
        copay_ratio=Decimal("0.2"), min_deductible=_NO_MIN,
        description="최종 fallback 규칙",
    )


def lookup_prescription_rule(generation: str) -> PrescriptionRule:
    """세대에 해당하는 처방약 공제 규칙을 반환한다."""
    gen = generation if generation in {"4th", "5th"} else "4th"
    return _PRESCRIPTION_INDEX[gen]
