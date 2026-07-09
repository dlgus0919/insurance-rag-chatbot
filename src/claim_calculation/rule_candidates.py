"""Review candidate helpers for source-grounded claim rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from src.claim_calculation.rule_registry import (
    ClaimDeductibleRule,
    ClaimPrescriptionRule,
    ClaimRuleValidationError,
    ClaimSpecialRule,
)


VALID_STATUSES = {"pending", "approved", "rejected", "applied"}
VALID_RULE_TYPES = {"deductible", "prescription", "special"}
VALID_OPERATIONS = {"add", "replace"}


class CandidateValidationError(ValueError):
    """Raised when a rule candidate cannot be safely reviewed or applied."""


@dataclass(frozen=True)
class CandidateApplyPlan:
    rules_to_add: list[dict[str, Any]]
    links_to_add: list[dict[str, Any]]
    rules_to_replace: list[dict[str, Any]]
    links_to_replace: list[dict[str, Any]]
    applied_candidate_ids: list[str]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CandidateValidationError(f"{path}:{line_no} invalid json") from exc
        if not isinstance(record, dict):
            raise CandidateValidationError(f"{path}:{line_no} record must be an object")
        records.append(record)
    return records


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def validate_candidate_record(record: dict[str, Any]) -> None:
    candidate_id = str(record.get("candidate_id") or "")
    if not candidate_id.startswith("rulecand."):
        raise CandidateValidationError("candidate_id must start with rulecand.")
    status = record.get("status")
    if status not in VALID_STATUSES:
        raise CandidateValidationError(f"invalid status: {status}")
    rule_type = record.get("rule_type")
    if rule_type not in VALID_RULE_TYPES:
        raise CandidateValidationError(f"invalid rule_type: {rule_type}")
    proposed_rule = record.get("proposed_rule")
    if not isinstance(proposed_rule, dict) or not proposed_rule.get("rule_id"):
        raise CandidateValidationError("proposed_rule.rule_id is required")
    proposed_links = record.get("proposed_links")
    if not isinstance(proposed_links, dict):
        raise CandidateValidationError("proposed_links is required")
    if proposed_links.get("rule_id") != proposed_rule.get("rule_id"):
        raise CandidateValidationError("proposed_links.rule_id must match proposed_rule.rule_id")
    operation = record.get("operation") or "add"
    if operation not in VALID_OPERATIONS:
        raise CandidateValidationError(f"invalid operation: {operation}")
    if operation == "replace" and record.get("target_rule_id") != proposed_rule.get("rule_id"):
        raise CandidateValidationError("target_rule_id must match proposed_rule.rule_id for replace candidates")
    if not (record.get("source_refs") or []) or not (proposed_links.get("source_refs") or []):
        raise CandidateValidationError("source evidence is required")
    if not str(record.get("evidence_text") or "").strip():
        raise CandidateValidationError("evidence_text is required")
    _validate_rule_payload(str(rule_type), proposed_rule)


def build_apply_plan(
    *,
    active_rules: list[dict[str, Any]],
    active_links: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> CandidateApplyPlan:
    seen_rules = _rule_ids(active_rules)
    seen_links = _rule_ids(active_links)
    rules_to_add: list[dict[str, Any]] = []
    links_to_add: list[dict[str, Any]] = []
    rules_to_replace: list[dict[str, Any]] = []
    links_to_replace: list[dict[str, Any]] = []
    applied_candidate_ids: list[str] = []
    for candidate in candidates:
        if candidate.get("status") != "approved":
            continue
        validate_candidate_record(candidate)
        rule = dict(candidate["proposed_rule"])
        link = dict(candidate["proposed_links"])
        rule_id = str(rule["rule_id"])
        operation = candidate.get("operation") or "add"
        rule["approval_status"] = "active"
        link["link_status"] = "active"
        _validate_rule_payload(str(candidate["rule_type"]), rule)
        if operation == "replace":
            if rule_id not in seen_rules:
                raise CandidateValidationError(f"replace target rule_id not found: {rule_id}")
            rules_to_replace.append(rule)
            links_to_replace.append(link)
            applied_candidate_ids.append(str(candidate["candidate_id"]))
            continue
        if rule_id in seen_rules:
            raise CandidateValidationError(f"duplicate rule_id: {rule_id}")
        if rule_id in seen_links:
            raise CandidateValidationError(f"duplicate rule link: {rule_id}")
        rules_to_add.append(rule)
        links_to_add.append(link)
        applied_candidate_ids.append(str(candidate["candidate_id"]))
        seen_rules.add(rule_id)
        seen_links.add(rule_id)
    return CandidateApplyPlan(rules_to_add, links_to_add, rules_to_replace, links_to_replace, applied_candidate_ids)


def _rule_ids(records: Iterable[dict[str, Any]]) -> set[str]:
    return {str(record.get("rule_id")) for record in records if record.get("rule_id")}


def _validate_rule_payload(rule_type: str, payload: dict[str, Any]) -> None:
    try:
        if rule_type == "deductible":
            ClaimDeductibleRule.from_payload(payload)
        elif rule_type == "prescription":
            ClaimPrescriptionRule.from_payload(payload)
        elif rule_type == "special":
            ClaimSpecialRule.from_payload(payload)
        else:
            raise CandidateValidationError(f"invalid rule_type: {rule_type}")
    except ClaimRuleValidationError as exc:
        raise CandidateValidationError(str(exc)) from exc
