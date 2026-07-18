"""Versioned source-evidence specifications for pending claim-rule candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src import config


@dataclass(frozen=True)
class EvidenceReviewRequirement:
    """A source-text condition that becomes a practitioner review requirement."""

    required_all: tuple[str, ...]
    required_any: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class RuleCandidateEvidenceSpec:
    """Non-financial extraction criteria for one source-grounded review scope."""

    scope: str
    generation: str
    generation_label: str
    category: str
    treatment_label: str
    rule_id_template: str
    candidate_id_template: str
    description_template: str
    extraction_reason: str
    primary_chunk_id: str
    supporting_chunk_ids: tuple[str, ...]
    primary_required_terms: tuple[str, ...]
    visit_types: tuple[str, ...]
    review_requirements: tuple[EvidenceReviewRequirement, ...]


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


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


def _load_review_requirements(value: Any, field_name: str) -> tuple[EvidenceReviewRequirement, ...]:
    requirements: list[EvidenceReviewRequirement] = []
    for index, raw in enumerate(_object_list(value, field_name)):
        requirements.append(
            EvidenceReviewRequirement(
                required_all=_text_list(raw.get("required_all"), f"{field_name}[{index}].required_all"),
                required_any=_text_list(raw.get("required_any"), f"{field_name}[{index}].required_any"),
                message=_required_text(raw.get("message"), f"{field_name}[{index}].message"),
            )
        )
    if not requirements:
        raise ValueError(f"{field_name} must not be empty")
    return tuple(requirements)


@lru_cache(maxsize=8)
def _load_rule_candidate_evidence_specs(path_text: str) -> tuple[RuleCandidateEvidenceSpec, ...]:
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"claim rule candidate evidence specs are missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"claim rule candidate evidence specs are invalid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("claim rule candidate evidence specs root must be an object")
    _required_text(payload.get("schema_version"), "schema_version")

    specs: list[RuleCandidateEvidenceSpec] = []
    seen_scopes: set[str] = set()
    for index, raw in enumerate(_object_list(payload.get("review_specs"), "review_specs")):
        prefix = f"review_specs[{index}]"
        scope = _required_text(raw.get("scope"), f"{prefix}.scope")
        if scope in seen_scopes:
            raise ValueError(f"review_specs has duplicated scope: {scope}")
        seen_scopes.add(scope)
        specs.append(
            RuleCandidateEvidenceSpec(
                scope=scope,
                generation=_required_text(raw.get("generation"), f"{prefix}.generation"),
                generation_label=_required_text(raw.get("generation_label"), f"{prefix}.generation_label"),
                category=_required_text(raw.get("category"), f"{prefix}.category"),
                treatment_label=_required_text(raw.get("treatment_label"), f"{prefix}.treatment_label"),
                rule_id_template=_required_text(raw.get("rule_id_template"), f"{prefix}.rule_id_template"),
                candidate_id_template=_required_text(raw.get("candidate_id_template"), f"{prefix}.candidate_id_template"),
                description_template=_required_text(raw.get("description_template"), f"{prefix}.description_template"),
                extraction_reason=_required_text(raw.get("extraction_reason"), f"{prefix}.extraction_reason"),
                primary_chunk_id=_required_text(raw.get("primary_chunk_id"), f"{prefix}.primary_chunk_id"),
                supporting_chunk_ids=_text_list(raw.get("supporting_chunk_ids"), f"{prefix}.supporting_chunk_ids"),
                primary_required_terms=_text_list(raw.get("primary_required_terms"), f"{prefix}.primary_required_terms"),
                visit_types=_text_list(raw.get("visit_types"), f"{prefix}.visit_types"),
                review_requirements=_load_review_requirements(
                    raw.get("review_requirements"),
                    f"{prefix}.review_requirements",
                ),
            )
        )
    if not specs:
        raise ValueError("review_specs must not be empty")
    return tuple(specs)


def load_rule_candidate_evidence_spec(
    scope: str,
    path: Path | str | None = None,
) -> RuleCandidateEvidenceSpec:
    """Load one versioned review input without placing insurance evidence in code."""

    spec_path = Path(path) if path is not None else config.CLAIM_RULE_CANDIDATE_EVIDENCE_SPECS_PATH
    for spec in _load_rule_candidate_evidence_specs(str(spec_path)):
        if spec.scope == scope:
            return spec
    raise ValueError(f"claim rule candidate evidence scope is missing: {scope}")
