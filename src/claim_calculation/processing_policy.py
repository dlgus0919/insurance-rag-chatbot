"""Versioned, non-financial processing policies for claim input normalization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src import config


@dataclass(frozen=True)
class StandardMatchConstraint:
    """One query-to-row filtering constraint loaded from a policy artifact."""

    constraint_id: str
    query_aliases: tuple[str, ...]
    row_required_any: tuple[str, ...]


@dataclass(frozen=True)
class TextRule:
    """A named text criterion used by the generic calculation interpreter."""

    rule_id: str
    terms_any: tuple[str, ...]


@dataclass(frozen=True)
class CategoryTextRule:
    """One ordered category classification criterion from the policy artifact."""

    rule_id: str
    category: str
    terms_any: tuple[str, ...]


@dataclass(frozen=True)
class ClaimProcessingPolicy:
    """Processing-only criteria; payout values remain in approved rule manifests."""

    schema_version: str
    standard_match_constraints: tuple[StandardMatchConstraint, ...]
    named_text_rules: tuple[TextRule, ...]
    category_text_rules: tuple[CategoryTextRule, ...]
    default_category: str
    explicit_code_required_categories: tuple[str, ...]


def _text_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    values = tuple(str(item).strip() for item in value if str(item).strip())
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    return values


def _object_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    objects: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{field_name}[{index}] must be an object")
        objects.append(item)
    return objects


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _load_text_rules(value: Any, field_name: str) -> tuple[TextRule, ...]:
    rules: list[TextRule] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(_object_list(value, field_name)):
        rule_id = _required_text(raw.get("id"), f"{field_name}[{index}].id")
        if rule_id in seen_ids:
            raise ValueError(f"{field_name} has duplicated id: {rule_id}")
        seen_ids.add(rule_id)
        rules.append(
            TextRule(
                rule_id=rule_id,
                terms_any=_text_list(raw.get("terms_any"), f"{field_name}[{index}].terms_any"),
            )
        )
    return tuple(rules)


def _load_category_text_rules(value: Any) -> tuple[CategoryTextRule, ...]:
    field_name = "category_text_rules"
    rules: list[CategoryTextRule] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(_object_list(value, field_name)):
        rule_id = _required_text(raw.get("id"), f"{field_name}[{index}].id")
        if rule_id in seen_ids:
            raise ValueError(f"{field_name} has duplicated id: {rule_id}")
        seen_ids.add(rule_id)
        rules.append(
            CategoryTextRule(
                rule_id=rule_id,
                category=_required_text(raw.get("category"), f"{field_name}[{index}].category"),
                terms_any=_text_list(raw.get("terms_any"), f"{field_name}[{index}].terms_any"),
            )
        )
    if not rules:
        raise ValueError("category_text_rules must not be empty")
    return tuple(rules)


@lru_cache(maxsize=8)
def _load_claim_processing_policy(path_text: str) -> ClaimProcessingPolicy:
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"claim processing policy is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"claim processing policy is invalid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("claim processing policy root must be an object")
    schema_version = _required_text(payload.get("schema_version"), "schema_version")

    raw_constraints = payload.get("standard_match_constraints")
    constraints: list[StandardMatchConstraint] = []
    for index, raw in enumerate(_object_list(raw_constraints, "standard_match_constraints")):
        constraint_id = _required_text(raw.get("id"), f"standard_match_constraints[{index}].id")
        constraints.append(
            StandardMatchConstraint(
                constraint_id=constraint_id,
                query_aliases=_text_list(raw.get("query_aliases"), f"standard_match_constraints[{index}].query_aliases"),
                row_required_any=_text_list(raw.get("row_required_any"), f"standard_match_constraints[{index}].row_required_any"),
            )
        )

    return ClaimProcessingPolicy(
        schema_version=schema_version,
        standard_match_constraints=tuple(constraints),
        named_text_rules=_load_text_rules(payload.get("named_text_rules"), "named_text_rules"),
        category_text_rules=_load_category_text_rules(payload.get("category_text_rules")),
        default_category=_required_text(payload.get("default_category"), "default_category"),
        explicit_code_required_categories=_text_list(
            payload.get("explicit_code_required_categories"),
            "explicit_code_required_categories",
        ),
    )


def load_claim_processing_policy(path: Path | str | None = None) -> ClaimProcessingPolicy:
    """Load a versioned processing policy without embedding insurance content in code."""

    policy_path = Path(path) if path is not None else config.CLAIM_PROCESSING_POLICY_PATH
    return _load_claim_processing_policy(str(policy_path))


def _normalize_text(value: str) -> str:
    return "".join((value or "").split()).casefold()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    normalized = _normalize_text(text)
    return bool(normalized) and any(_normalize_text(term) in normalized for term in terms)


def standard_match_constraint_for_query(input_name: str) -> StandardMatchConstraint | None:
    normalized = _normalize_text(input_name)
    if not normalized:
        return None
    for constraint in load_claim_processing_policy().standard_match_constraints:
        if normalized in {_normalize_text(alias) for alias in constraint.query_aliases}:
            return constraint
    return None


def text_rule_matches(rule_id: str, text: str) -> bool:
    """Evaluate a named processing criterion without embedding its terms in code."""

    for rule in load_claim_processing_policy().named_text_rules:
        if rule.rule_id == rule_id:
            return _contains_any(text, rule.terms_any)
    raise ValueError(f"named text rule is missing: {rule_id}")


def category_for_text(text: str) -> str:
    """Return the first category whose policy criterion matches the input text."""

    policy = load_claim_processing_policy()
    for rule in policy.category_text_rules:
        if _contains_any(text, rule.terms_any):
            return rule.category
    return policy.default_category


def requires_explicit_code_for_category(category: str) -> bool:
    return (category or "").strip() in set(
        load_claim_processing_policy().explicit_code_required_categories
    )
