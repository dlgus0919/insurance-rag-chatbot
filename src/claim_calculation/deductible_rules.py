"""Claim deductible rule compatibility API backed by approved manifests."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from src import config
from src.claim_calculation.rule_registry import (
    ClaimDeductibleRule,
    ClaimPrescriptionRule,
    ClaimRuleRegistry,
    ClaimSpecialRule,
)


FACILITY_CLINIC = "clinic"
FACILITY_HOSPITAL = "hospital"
FACILITY_GENERAL = "general_hospital"
FACILITY_TERTIARY = "tertiary_hospital"

FACILITY_GRADES = (FACILITY_CLINIC, FACILITY_HOSPITAL, FACILITY_GENERAL, FACILITY_TERTIARY)
DEFAULT_FACILITY = FACILITY_CLINIC

CLAIM_RULES_PATH = config.ROOT_DIR / "data" / "rules" / "claim_deductible_rules.active.json"


@dataclass(frozen=True)
class DeductibleRule:
    """Runtime view of one approved deductible rule row."""

    generation: str
    category: str
    visit_type: str
    copay_ratio: Decimal
    min_deductible: dict[str, Decimal]
    per_visit_limit: Decimal | None = None
    annual_limit: Decimal | None = None
    annual_visit_limit: int | None = None
    review_requirements: tuple[str, ...] = ()
    description: str = ""
    source_doc: str = ""
    source_page: str | None = None
    source_clause: str = ""
    source_chunk_id: str = ""
    source_status: str = ""

    def get_min_deductible(self, facility_grade: str = "") -> Decimal:
        grade = facility_grade if facility_grade in self.min_deductible else DEFAULT_FACILITY
        return self.min_deductible.get(grade, Decimal("0"))


@dataclass(frozen=True)
class PrescriptionRule:
    """Runtime view of one approved prescription deductible rule row."""

    generation: str
    deductible_amount: Decimal
    per_visit_limit: Decimal | None = None
    description: str = ""
    source_doc: str = ""
    source_page: str | None = None
    source_clause: str = ""
    source_chunk_id: str = ""
    source_status: str = ""


@dataclass(frozen=True)
class SpecialRule:
    """Runtime view of one approved special calculation rule."""

    special_type: str
    payout_ratio: Decimal | None = None
    daily_limit: Decimal | None = None
    description: str = ""
    source_doc: str = ""
    source_page: str | None = None
    source_clause: str = ""
    source_chunk_id: str = ""
    source_status: str = ""


_NO_MIN = {grade: Decimal("0") for grade in FACILITY_GRADES}
_4TH_NON_BENEFIT_ALIASES = {"3대비급여", "중증비급여", "비중증비급여"}
_4TH_EXACT_ONLY_CATEGORIES = {"3대비급여_도수"}


@lru_cache(maxsize=1)
def _load_registry() -> ClaimRuleRegistry:
    return ClaimRuleRegistry.from_file(Path(CLAIM_RULES_PATH))


def _normalize_generation(generation: str) -> str:
    return generation if generation in {"4th", "5th"} else "5th"


def _normalize_visit_type(visit_type: str) -> str:
    return visit_type if visit_type in {"hospitalization", "outpatient"} else "outpatient"


def _rule_to_runtime(rule: ClaimDeductibleRule, facility_grade: str = "") -> DeductibleRule:
    min_by_facility = dict(rule.min_deductible_by_facility)
    if not min_by_facility:
        if rule.facility_grade in FACILITY_GRADES:
            min_by_facility = dict(_NO_MIN)
            min_by_facility[rule.facility_grade] = rule.min_deductible
        else:
            min_by_facility = {grade: rule.min_deductible for grade in FACILITY_GRADES}
    elif facility_grade and facility_grade not in min_by_facility:
        min_by_facility[facility_grade] = rule.min_deductible
    return DeductibleRule(
        generation=rule.generation,
        category=rule.category,
        visit_type=rule.visit_type,
        copay_ratio=rule.copay_ratio,
        min_deductible=min_by_facility,
        per_visit_limit=rule.per_visit_limit,
        annual_limit=rule.annual_limit,
        annual_visit_limit=rule.annual_visit_limit,
        review_requirements=rule.review_requirements,
        description=rule.description,
        source_doc=rule.source_doc,
        source_page=rule.source_page,
        source_clause=rule.source_clause,
        source_chunk_id=rule.source_chunk_id,
        source_status=rule.source_status,
    )


def _prescription_to_runtime(rule: ClaimPrescriptionRule) -> PrescriptionRule:
    return PrescriptionRule(
        generation=rule.generation,
        deductible_amount=rule.deductible_amount,
        per_visit_limit=rule.per_visit_limit,
        description=rule.description,
        source_doc=rule.source_doc,
        source_page=rule.source_page,
        source_clause=rule.source_clause,
        source_chunk_id=rule.source_chunk_id,
        source_status=rule.source_status,
    )


def _special_to_runtime(rule: ClaimSpecialRule) -> SpecialRule:
    return SpecialRule(
        special_type=rule.special_type,
        payout_ratio=rule.payout_ratio,
        daily_limit=rule.daily_limit,
        description=rule.description,
        source_doc=rule.source_doc,
        source_page=rule.source_page,
        source_clause=rule.source_clause,
        source_chunk_id=rule.source_chunk_id,
        source_status=rule.source_status,
    )


def lookup_rule(
    generation: str,
    category: str,
    visit_type: str,
    facility_grade: str = "",
) -> DeductibleRule:
    """Return a deductible rule for generation/category/visit type.

    The function preserves the legacy fallback behavior while sourcing values
    from the active rule manifest.
    """

    gen = _normalize_generation(generation)
    vt = _normalize_visit_type(visit_type)
    registry = _load_registry()

    candidates = [category]
    if not (gen == "4th" and category in _4TH_EXACT_ONLY_CATEGORIES):
        if gen == "4th" and category in _4TH_NON_BENEFIT_ALIASES:
            candidates.append("비급여")
        candidates.append("급여")

    for candidate in dict.fromkeys(candidates):
        try:
            return _rule_to_runtime(registry.lookup(gen, candidate, vt, facility_grade), facility_grade)
        except KeyError:
            continue

    raise KeyError((gen, category, vt, facility_grade))


def has_exact_rule(
    generation: str,
    category: str,
    visit_type: str,
    facility_grade: str = "",
) -> bool:
    """Return whether the active manifest has this exact category rule."""

    gen = _normalize_generation(generation)
    vt = _normalize_visit_type(visit_type)
    try:
        _load_registry().lookup(gen, category, vt, facility_grade)
    except KeyError:
        return False
    return True


def lookup_prescription_rule(generation: str) -> PrescriptionRule:
    """Return the approved prescription deductible rule for a generation."""

    gen = _normalize_generation(generation)
    return _prescription_to_runtime(_load_registry().lookup_prescription(gen))


def lookup_special_rule(special_type: str) -> SpecialRule:
    """Return an approved special calculation rule."""

    return _special_to_runtime(_load_registry().lookup_special(special_type))
