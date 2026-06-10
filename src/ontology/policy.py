from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.ontology.registry import ONTOLOGY_DIR


POLICY_DIR = ONTOLOGY_DIR / "policies"
DEFAULT_CANDIDATE_EXTRACTION_POLICY = POLICY_DIR / "candidate_extraction_policy.json"
DEFAULT_REVIEW_POLICY = POLICY_DIR / "review_policy.json"


@dataclass(frozen=True)
class ExpressionShapePolicy:
    min_length: int = 3
    max_length: int = 18
    allow_digits: bool = False
    allow_ascii_letters: bool = False
    max_terms: int = 3
    blocked_prefixes: tuple[str, ...] = field(default_factory=tuple)
    blocked_suffixes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExpressionShapePolicy":
        return cls(
            min_length=_as_int(payload.get("min_length"), default=3),
            max_length=_as_int(payload.get("max_length"), default=18),
            allow_digits=bool(payload.get("allow_digits") is True),
            allow_ascii_letters=bool(payload.get("allow_ascii_letters") is True),
            max_terms=_as_int(payload.get("max_terms"), default=3),
            blocked_prefixes=tuple(_string_list(payload.get("blocked_prefixes"))),
            blocked_suffixes=tuple(_string_list(payload.get("blocked_suffixes"))),
        )

    def validate(self, *, field_name: str) -> list[str]:
        errors: list[str] = []
        if self.min_length < 1:
            errors.append(f"{field_name}.min_length must be >= 1")
        if self.max_length < self.min_length:
            errors.append(f"{field_name}.max_length must be >= min_length")
        if self.max_terms < 1:
            errors.append(f"{field_name}.max_terms must be >= 1")
        return errors


@dataclass(frozen=True)
class CandidateExtractionPolicy:
    schema_version: str
    policy_id: str
    version: str
    domain_keywords: tuple[str, ...]
    stop_phrases: tuple[str, ...]
    generic_table_terms: tuple[str, ...]
    noise_fragments: tuple[str, ...]
    table_noise_markers: tuple[str, ...]
    expression_shape: ExpressionShapePolicy
    default_reinforcement_type: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateExtractionPolicy":
        candidate_types = payload.get("candidate_types") if isinstance(payload.get("candidate_types"), dict) else {}
        expression_shape = payload.get("expression_shape") if isinstance(payload.get("expression_shape"), dict) else {}
        return cls(
            schema_version=str(payload.get("schema_version") or "").strip(),
            policy_id=str(payload.get("policy_id") or "").strip(),
            version=str(payload.get("version") or "").strip(),
            domain_keywords=tuple(_string_list(payload.get("domain_keywords"))),
            stop_phrases=tuple(_string_list(payload.get("stop_phrases"))),
            generic_table_terms=tuple(_string_list(payload.get("generic_table_terms"))),
            noise_fragments=tuple(_string_list(payload.get("noise_fragments"))),
            table_noise_markers=tuple(_string_list(payload.get("table_noise_markers"))),
            expression_shape=ExpressionShapePolicy.from_dict(expression_shape),
            default_reinforcement_type=str(candidate_types.get("default_reinforcement_type") or "").strip(),
        )

    def validate(self) -> list[str]:
        errors = _validate_common(self.schema_version, self.policy_id, self.version, field_name="candidate_extraction_policy")
        if not self.domain_keywords:
            errors.append("candidate_extraction_policy.domain_keywords must not be empty")
        if not self.stop_phrases:
            errors.append("candidate_extraction_policy.stop_phrases must not be empty")
        if not self.default_reinforcement_type:
            errors.append("candidate_extraction_policy.candidate_types.default_reinforcement_type is required")
        errors.extend(self.expression_shape.validate(field_name="candidate_extraction_policy.expression_shape"))
        return errors


@dataclass(frozen=True)
class AutoApprovalPolicy:
    require_pending_status: bool = True
    require_source_evidence: bool = True
    require_test_candidate: bool = True
    require_dev_risk_flag: bool = True
    require_target_overlap: bool = True
    development_only: bool = True
    allowed_risk_levels: tuple[str, ...] = field(default_factory=lambda: ("low", "dev_only"))
    risk_flags: tuple[str, ...] = field(default_factory=lambda: ("dev_only", "dev_auto_approval"))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AutoApprovalPolicy":
        return cls(
            require_pending_status=bool(payload.get("require_pending_status") is not False),
            require_source_evidence=bool(payload.get("require_source_evidence") is not False),
            require_test_candidate=bool(payload.get("require_test_candidate") is not False),
            require_dev_risk_flag=bool(payload.get("require_dev_risk_flag") is not False),
            require_target_overlap=bool(payload.get("require_target_overlap") is not False),
            development_only=bool(payload.get("development_only") is not False),
            allowed_risk_levels=tuple(_string_list(payload.get("allowed_risk_levels"))),
            risk_flags=tuple(_string_list(payload.get("risk_flags"))),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.allowed_risk_levels:
            errors.append("review_policy.auto_approval.allowed_risk_levels must not be empty")
        if self.require_dev_risk_flag and not self.risk_flags:
            errors.append("review_policy.auto_approval.risk_flags must not be empty when require_dev_risk_flag is true")
        return errors


@dataclass(frozen=True)
class OntologyReviewPolicy:
    schema_version: str
    policy_id: str
    version: str
    low_risk_candidate_types: tuple[str, ...]
    prohibited_auto_approval_types: tuple[str, ...]
    prohibited_risk_terms: tuple[str, ...]
    unsafe_auto_approval_fragments: tuple[str, ...]
    expression_shape: ExpressionShapePolicy
    auto_approval: AutoApprovalPolicy

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OntologyReviewPolicy":
        expression_shape = payload.get("expression_shape") if isinstance(payload.get("expression_shape"), dict) else {}
        auto_approval = payload.get("auto_approval") if isinstance(payload.get("auto_approval"), dict) else {}
        return cls(
            schema_version=str(payload.get("schema_version") or "").strip(),
            policy_id=str(payload.get("policy_id") or "").strip(),
            version=str(payload.get("version") or "").strip(),
            low_risk_candidate_types=tuple(_string_list(payload.get("low_risk_candidate_types"))),
            prohibited_auto_approval_types=tuple(_string_list(payload.get("prohibited_auto_approval_types"))),
            prohibited_risk_terms=tuple(_string_list(payload.get("prohibited_risk_terms"))),
            unsafe_auto_approval_fragments=tuple(_string_list(payload.get("unsafe_auto_approval_fragments"))),
            expression_shape=ExpressionShapePolicy.from_dict(expression_shape),
            auto_approval=AutoApprovalPolicy.from_dict(auto_approval),
        )

    def validate(self) -> list[str]:
        errors = _validate_common(self.schema_version, self.policy_id, self.version, field_name="review_policy")
        if not self.low_risk_candidate_types:
            errors.append("review_policy.low_risk_candidate_types must not be empty")
        if not self.prohibited_auto_approval_types:
            errors.append("review_policy.prohibited_auto_approval_types must not be empty")
        if not self.prohibited_risk_terms:
            errors.append("review_policy.prohibited_risk_terms must not be empty")
        overlap = set(self.low_risk_candidate_types).intersection(self.prohibited_auto_approval_types)
        if overlap:
            errors.append(f"review_policy candidate type conflict: {', '.join(sorted(overlap))}")
        errors.extend(self.expression_shape.validate(field_name="review_policy.expression_shape"))
        errors.extend(self.auto_approval.validate())
        return errors


def load_candidate_extraction_policy(path: str | Path | None = None) -> CandidateExtractionPolicy:
    policy_path = Path(path) if path else DEFAULT_CANDIDATE_EXTRACTION_POLICY
    payload = _read_json(policy_path)
    errors = validate_candidate_extraction_policy(payload)
    if errors:
        raise ValueError("Invalid candidate extraction policy: " + "; ".join(errors))
    return CandidateExtractionPolicy.from_dict(payload)


def load_review_policy(path: str | Path | None = None) -> OntologyReviewPolicy:
    policy_path = Path(path) if path else DEFAULT_REVIEW_POLICY
    payload = _read_json(policy_path)
    errors = validate_review_policy(payload)
    if errors:
        raise ValueError("Invalid ontology review policy: " + "; ".join(errors))
    return OntologyReviewPolicy.from_dict(payload)


def validate_candidate_extraction_policy(payload: dict[str, Any]) -> list[str]:
    if not isinstance(payload, dict):
        return ["policy payload must be an object"]
    return CandidateExtractionPolicy.from_dict(payload).validate()


def validate_review_policy(payload: dict[str, Any]) -> list[str]:
    if not isinstance(payload, dict):
        return ["policy payload must be an object"]
    return OntologyReviewPolicy.from_dict(payload).validate()


def validate_policy_files(
    *,
    candidate_policy_path: str | Path | None = None,
    review_policy_path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    candidate_policy = load_candidate_extraction_policy(candidate_policy_path)
    review_policy = load_review_policy(review_policy_path)
    return {
        "candidate_extraction_policy": {
            "policy_id": candidate_policy.policy_id,
            "version": candidate_policy.version,
        },
        "review_policy": {
            "policy_id": review_policy.policy_id,
            "version": review_policy.version,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"policy file must contain a JSON object: {path}")
    return payload


def _as_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _validate_common(schema_version: str, policy_id: str, version: str, *, field_name: str) -> list[str]:
    errors: list[str] = []
    if not schema_version:
        errors.append(f"{field_name}.schema_version is required")
    if not policy_id:
        errors.append(f"{field_name}.policy_id is required")
    if not version:
        errors.append(f"{field_name}.version is required")
    return errors
