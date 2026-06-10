from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ontology.policy import (
    load_candidate_extraction_policy,
    load_review_policy,
    validate_candidate_extraction_policy,
    validate_review_policy,
)


def test_load_default_candidate_extraction_policy() -> None:
    policy = load_candidate_extraction_policy()

    assert policy.policy_id == "candidate-extraction-default"
    assert policy.version == "2026-06-10"
    assert "상해" in policy.domain_keywords
    assert policy.default_reinforcement_type == "alias_or_expansion"


def test_load_default_review_policy() -> None:
    policy = load_review_policy()

    assert policy.policy_id == "ontology-review-default"
    assert policy.version == "2026-06-10"
    assert "alias_or_expansion" in policy.low_risk_candidate_types
    assert "payment_logic" in policy.prohibited_auto_approval_types
    assert policy.auto_approval.require_test_candidate is True


def test_candidate_extraction_policy_rejects_empty_domain_keywords() -> None:
    payload = {
        "schema_version": "1.0",
        "policy_id": "bad-candidate-policy",
        "version": "test",
        "domain_keywords": [],
        "stop_phrases": ["보험"],
        "candidate_types": {"default_reinforcement_type": "alias_or_expansion"},
        "expression_shape": {"min_length": 3, "max_length": 18},
    }

    errors = validate_candidate_extraction_policy(payload)

    assert "candidate_extraction_policy.domain_keywords must not be empty" in errors


def test_candidate_extraction_policy_rejects_invalid_expression_shape() -> None:
    payload = {
        "schema_version": "1.0",
        "policy_id": "bad-candidate-policy",
        "version": "test",
        "domain_keywords": ["상해"],
        "stop_phrases": ["보험"],
        "candidate_types": {"default_reinforcement_type": "alias_or_expansion"},
        "expression_shape": {"min_length": 10, "max_length": 3},
    }

    errors = validate_candidate_extraction_policy(payload)

    assert "candidate_extraction_policy.expression_shape.max_length must be >= min_length" in errors


def test_review_policy_rejects_candidate_type_conflict() -> None:
    payload = {
        "schema_version": "1.0",
        "policy_id": "bad-review-policy",
        "version": "test",
        "low_risk_candidate_types": ["alias_or_expansion"],
        "prohibited_auto_approval_types": ["alias_or_expansion"],
        "prohibited_risk_terms": ["보험금"],
        "expression_shape": {"min_length": 3, "max_length": 18},
        "auto_approval": {"allowed_risk_levels": ["low"], "risk_flags": ["dev_auto_approval"]},
    }

    errors = validate_review_policy(payload)

    assert "review_policy candidate type conflict: alias_or_expansion" in errors


def test_review_policy_file_validation_raises_for_empty_risk_terms(tmp_path: Path) -> None:
    path = tmp_path / "review_policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "policy_id": "bad-review-policy",
                "version": "test",
                "low_risk_candidate_types": ["alias_or_expansion"],
                "prohibited_auto_approval_types": ["payment_logic"],
                "prohibited_risk_terms": [],
                "expression_shape": {"min_length": 3, "max_length": 18},
                "auto_approval": {"allowed_risk_levels": ["low"], "risk_flags": ["dev_auto_approval"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="prohibited_risk_terms"):
        load_review_policy(path)
