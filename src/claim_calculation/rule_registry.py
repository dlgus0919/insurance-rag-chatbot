"""Source-grounded claim deductible rule registry."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ACTIVE_STATUS = "active"
ALL_FACILITIES = "all"


class ClaimRuleValidationError(ValueError):
    """Raised when a claim rule manifest row is not safe to load."""


@dataclass(frozen=True)
class ClaimDeductibleRule:
    """Approved deductible rule row loaded from a manifest."""

    rule_id: str
    generation: str
    category: str
    visit_type: str
    facility_grade: str
    copay_ratio: Decimal
    min_deductible: Decimal
    min_deductible_by_facility: dict[str, Decimal] = field(default_factory=dict)
    per_visit_limit: Decimal | None = None
    annual_limit: Decimal | None = None
    annual_visit_limit: int | None = None
    review_requirements: tuple[str, ...] = ()
    description: str = ""
    source_doc: str = ""
    source_page: str = ""
    source_clause: str = ""
    source_chunk_id: str = ""
    approval_status: str = ""
    source_status: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClaimDeductibleRule":
        _require_source_reference(payload)
        min_by_facility = payload.get("min_deductible_by_facility") or {}
        if not isinstance(min_by_facility, dict):
            raise ClaimRuleValidationError("min_deductible_by_facility must be an object")
        return cls(
            rule_id=_required_text(payload, "rule_id"),
            generation=_required_text(payload, "generation"),
            category=_required_text(payload, "category"),
            visit_type=_required_text(payload, "visit_type"),
            facility_grade=_required_text(payload, "facility_grade"),
            copay_ratio=_decimal(payload.get("copay_ratio"), "copay_ratio"),
            min_deductible=_decimal(payload.get("min_deductible"), "min_deductible"),
            min_deductible_by_facility={
                str(key): _decimal(value, f"min_deductible_by_facility.{key}")
                for key, value in min_by_facility.items()
            },
            per_visit_limit=_optional_decimal(payload.get("per_visit_limit"), "per_visit_limit"),
            annual_limit=_optional_decimal(payload.get("annual_limit"), "annual_limit"),
            annual_visit_limit=_optional_int(payload.get("annual_visit_limit"), "annual_visit_limit"),
            review_requirements=_optional_text_list(payload.get("review_requirements"), "review_requirements"),
            description=str(payload.get("description") or ""),
            source_doc=_required_text(payload, "source_doc"),
            source_page=_required_text(payload, "source_page"),
            source_clause=_required_text(payload, "source_clause"),
            source_chunk_id=_required_text(payload, "source_chunk_id"),
            approval_status=_required_text(payload, "approval_status"),
            source_status=str(payload.get("source_status") or ""),
        )


@dataclass(frozen=True)
class ClaimPrescriptionRule:
    """Approved prescription deductible rule row."""

    rule_id: str
    generation: str
    deductible_amount: Decimal
    per_visit_limit: Decimal | None = None
    description: str = ""
    source_doc: str = ""
    source_page: str = ""
    source_clause: str = ""
    source_chunk_id: str = ""
    approval_status: str = ""
    source_status: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClaimPrescriptionRule":
        _require_source_reference(payload)
        return cls(
            rule_id=_required_text(payload, "rule_id"),
            generation=_required_text(payload, "generation"),
            deductible_amount=_decimal(payload.get("deductible_amount"), "deductible_amount"),
            per_visit_limit=_optional_decimal(payload.get("per_visit_limit"), "per_visit_limit"),
            description=str(payload.get("description") or ""),
            source_doc=_required_text(payload, "source_doc"),
            source_page=_required_text(payload, "source_page"),
            source_clause=_required_text(payload, "source_clause"),
            source_chunk_id=_required_text(payload, "source_chunk_id"),
            approval_status=_required_text(payload, "approval_status"),
            source_status=str(payload.get("source_status") or ""),
        )


@dataclass(frozen=True)
class ClaimSpecialRule:
    """Approved special calculation rule row."""

    rule_id: str
    special_type: str
    payout_ratio: Decimal | None = None
    daily_limit: Decimal | None = None
    description: str = ""
    source_doc: str = ""
    source_page: str = ""
    source_clause: str = ""
    source_chunk_id: str = ""
    approval_status: str = ""
    source_status: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClaimSpecialRule":
        _require_source_reference(payload)
        return cls(
            rule_id=_required_text(payload, "rule_id"),
            special_type=_required_text(payload, "special_type"),
            payout_ratio=_optional_decimal(payload.get("payout_ratio"), "payout_ratio"),
            daily_limit=_optional_decimal(payload.get("daily_limit"), "daily_limit"),
            description=str(payload.get("description") or ""),
            source_doc=_required_text(payload, "source_doc"),
            source_page=_required_text(payload, "source_page"),
            source_clause=_required_text(payload, "source_clause"),
            source_chunk_id=_required_text(payload, "source_chunk_id"),
            approval_status=_required_text(payload, "approval_status"),
            source_status=str(payload.get("source_status") or ""),
        )


class ClaimRuleRegistry:
    """Load and index active claim calculation rules."""

    def __init__(
        self,
        rules: list[ClaimDeductibleRule],
        prescription_rules: list[ClaimPrescriptionRule] | None = None,
        special_rules: list[ClaimSpecialRule] | None = None,
    ) -> None:
        self._rules: dict[tuple[str, str, str, str], ClaimDeductibleRule] = {}
        self._fallback_rules: dict[tuple[str, str, str], ClaimDeductibleRule] = {}
        self._prescription_rules: dict[str, ClaimPrescriptionRule] = {}
        self._special_rules: dict[str, ClaimSpecialRule] = {}
        for rule in rules:
            if rule.approval_status != ACTIVE_STATUS:
                continue
            key = (rule.generation, rule.category, rule.visit_type, rule.facility_grade)
            self._rules[key] = rule
            if rule.facility_grade == ALL_FACILITIES:
                self._fallback_rules[(rule.generation, rule.category, rule.visit_type)] = rule
        for rule in prescription_rules or []:
            if rule.approval_status == ACTIVE_STATUS:
                self._prescription_rules[rule.generation] = rule
        for rule in special_rules or []:
            if rule.approval_status == ACTIVE_STATUS:
                self._special_rules[rule.special_type] = rule

    @classmethod
    def from_file(cls, path: Path | str) -> "ClaimRuleRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            raise ClaimRuleValidationError("unsupported claim rule manifest version")
        raw_rules = payload.get("rules")
        if not isinstance(raw_rules, list):
            raise ClaimRuleValidationError("rules must be a list")
        rules = [ClaimDeductibleRule.from_payload(row) for row in raw_rules]
        raw_prescription_rules = payload.get("prescription_rules") or []
        if not isinstance(raw_prescription_rules, list):
            raise ClaimRuleValidationError("prescription_rules must be a list")
        prescriptions = [ClaimPrescriptionRule.from_payload(row) for row in raw_prescription_rules]
        raw_special_rules = payload.get("special_rules") or []
        if not isinstance(raw_special_rules, list):
            raise ClaimRuleValidationError("special_rules must be a list")
        special_rules = [ClaimSpecialRule.from_payload(row) for row in raw_special_rules]
        return cls(rules, prescriptions, special_rules)

    def lookup(
        self,
        generation: str,
        category: str,
        visit_type: str,
        facility_grade: str = "",
    ) -> ClaimDeductibleRule:
        grade = facility_grade or ALL_FACILITIES
        exact = self._rules.get((generation, category, visit_type, grade))
        if exact:
            return exact
        fallback = self._fallback_rules.get((generation, category, visit_type))
        if fallback:
            return fallback
        raise KeyError((generation, category, visit_type, facility_grade))

    def lookup_prescription(self, generation: str) -> ClaimPrescriptionRule:
        try:
            return self._prescription_rules[generation]
        except KeyError as exc:
            raise KeyError(generation) from exc

    def lookup_special(self, special_type: str) -> ClaimSpecialRule:
        try:
            return self._special_rules[special_type]
        except KeyError as exc:
            raise KeyError(special_type) from exc

    def active_rules(self) -> list[ClaimDeductibleRule]:
        result: list[ClaimDeductibleRule] = []
        seen: set[str] = set()
        for rule in list(self._rules.values()) + list(self._fallback_rules.values()):
            if rule.rule_id not in seen:
                result.append(rule)
                seen.add(rule.rule_id)
        return result


def _required_text(payload: dict[str, Any], field_name: str) -> str:
    value = str(payload.get(field_name) or "").strip()
    if not value:
        raise ClaimRuleValidationError(f"{field_name} is required")
    return value


def _require_source_reference(payload: dict[str, Any]) -> None:
    for field_name in ("source_doc", "source_page", "source_clause", "source_chunk_id"):
        _required_text(payload, field_name)


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ClaimRuleValidationError(f"{field_name} must be decimal") from exc


def _optional_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    return _decimal(value, field_name)


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ClaimRuleValidationError(f"{field_name} must be integer") from exc


def _optional_text_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ClaimRuleValidationError(f"{field_name} must be a list of text")
    return tuple(item.strip() for item in value if item.strip())
