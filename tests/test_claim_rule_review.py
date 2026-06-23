from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.claim_rule_review import update_rule_value
from src.claim_calculation.rule_registry import ClaimRuleRegistry


def _manifest() -> dict:
    return {
        "version": 1,
        "rules": [
            {
                "rule_id": "deductible.test",
                "generation": "4th",
                "category": "benefit",
                "visit_type": "outpatient",
                "facility_grade": "all",
                "copay_ratio": "0.2",
                "min_deductible": "10000",
                "min_deductible_by_facility": {},
                "per_visit_limit": None,
                "annual_limit": None,
                "annual_visit_limit": None,
                "description": "test rule",
                "source_doc": "policy.pdf",
                "source_page": "1",
                "source_clause": "test clause",
                "source_chunk_id": "chunk-1",
                "approval_status": "active",
                "source_status": "verified",
            }
        ],
        "prescription_rules": [],
        "special_rules": [],
    }


def test_update_rule_value_writes_backup_log_and_valid_manifest(tmp_path: Path) -> None:
    rules_path = tmp_path / "claim_deductible_rules.active.json"
    rules_path.write_text(json.dumps(_manifest(), ensure_ascii=False), encoding="utf-8")

    event = update_rule_value(
        path=rules_path,
        rule_id="deductible.test",
        field="copay_ratio",
        raw_value="0.3",
        reviewer="tester",
        note="원문 근거 확인 후 정정",
    )

    payload = json.loads(rules_path.read_text(encoding="utf-8"))
    assert payload["rules"][0]["copay_ratio"] == "0.3"
    assert payload["rules"][0]["last_reviewed_by"] == "tester"
    assert event["old_value"] == "0.2"
    assert event["new_value"] == "0.3"
    assert list((tmp_path / "backups").glob("claim_deductible_rules.active.*.json"))
    log_lines = (tmp_path / "claim_rule_review_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(log_lines[-1])["rule_id"] == "deductible.test"
    ClaimRuleRegistry.from_file(rules_path)


def test_update_rule_value_requires_review_note(tmp_path: Path) -> None:
    rules_path = tmp_path / "claim_deductible_rules.active.json"
    rules_path.write_text(json.dumps(_manifest(), ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="review note"):
        update_rule_value(
            path=rules_path,
            rule_id="deductible.test",
            field="copay_ratio",
            raw_value="0.3",
            reviewer="tester",
            note="",
        )
