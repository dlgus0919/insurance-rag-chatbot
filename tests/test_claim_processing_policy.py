from __future__ import annotations

import json

import pytest

from src.claim_calculation import processing_policy


def test_processing_policy_owns_claim_category_and_mri_constraints() -> None:
    processing_policy._load_claim_processing_policy.cache_clear()

    assert processing_policy.category_for_text("도수치료") == "3대비급여_도수"
    assert processing_policy.category_for_text("비급여 주사료") == "3대비급여"
    assert processing_policy.text_rule_matches("mri_mra", "자기공명영상 검사") is True
    assert processing_policy.requires_explicit_code_for_category("3대비급여_도수") is True


def test_processing_policy_rejects_missing_category_schema(tmp_path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "standard_match_constraints": [],
                "named_text_rules": [],
                "explicit_code_required_categories": ["3대비급여"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    processing_policy._load_claim_processing_policy.cache_clear()

    with pytest.raises(ValueError, match="category_text_rules"):
        processing_policy.load_claim_processing_policy(path)
