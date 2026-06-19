from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.claim_calculation.rule_registry import ClaimRuleRegistry, ClaimRuleValidationError


def _write_rules(path, rows, prescription_rows=None, special_rows=None):
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": rows,
                "prescription_rules": prescription_rows or [],
                "special_rules": special_rows or [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _active_rule(**overrides):
    row = {
        "rule_id": "deductible.4th.outpatient.non_benefit",
        "generation": "4th",
        "category": "비급여",
        "visit_type": "outpatient",
        "facility_grade": "clinic",
        "copay_ratio": "0.3",
        "min_deductible": "30000",
        "per_visit_limit": "250000",
        "annual_limit": None,
        "annual_visit_limit": 180,
        "source_doc": "약관",
        "source_page": "p.12",
        "source_clause": "제5조",
        "source_chunk_id": "chunk-1",
        "approval_status": "active",
    }
    row.update(overrides)
    return row


def test_registry_loads_active_rule_with_source_reference(tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path, [_active_rule()])

    registry = ClaimRuleRegistry.from_file(rules_path)
    rule = registry.lookup("4th", "비급여", "outpatient", "clinic")

    assert rule.rule_id == "deductible.4th.outpatient.non_benefit"
    assert rule.copay_ratio == Decimal("0.3")
    assert rule.min_deductible == Decimal("30000")
    assert rule.source_chunk_id == "chunk-1"


def test_registry_uses_all_facility_rule_as_fallback(tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(
        rules_path,
        [
            _active_rule(
                rule_id="deductible.5th.benefit.outpatient",
                generation="5th",
                category="급여",
                facility_grade="all",
                copay_ratio="0.2",
                min_deductible="10000",
                min_deductible_by_facility={"clinic": "10000", "hospital": "15000"},
            )
        ],
    )

    registry = ClaimRuleRegistry.from_file(rules_path)
    rule = registry.lookup("5th", "급여", "outpatient", "hospital")

    assert rule.facility_grade == "all"
    assert rule.min_deductible_by_facility["hospital"] == Decimal("15000")
    assert len(registry.active_rules()) == 1


def test_registry_rejects_rule_without_source_reference(tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path, [_active_rule(source_doc="", source_page="", source_clause="", source_chunk_id="")])

    with pytest.raises(ClaimRuleValidationError, match="source"):
        ClaimRuleRegistry.from_file(rules_path)


def test_registry_ignores_non_active_rules(tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path, [_active_rule(approval_status="pending")])

    registry = ClaimRuleRegistry.from_file(rules_path)

    with pytest.raises(KeyError):
        registry.lookup("4th", "비급여", "outpatient", "clinic")


def test_registry_loads_prescription_rules(tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(
        rules_path,
        [],
        [
            {
                "rule_id": "prescription.5th",
                "generation": "5th",
                "deductible_amount": "8000",
                "per_visit_limit": "50000",
                "source_doc": "약관",
                "source_page": "p.31",
                "source_clause": "제3조",
                "source_chunk_id": "chunk-rx",
                "approval_status": "active",
            }
        ],
    )

    registry = ClaimRuleRegistry.from_file(rules_path)
    rule = registry.lookup_prescription("5th")

    assert rule.deductible_amount == Decimal("8000")
    assert rule.per_visit_limit == Decimal("50000")


def test_registry_loads_special_rules(tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(
        rules_path,
        [],
        special_rows=[
            {
                "rule_id": "special.upper_room_difference",
                "special_type": "upper_room_difference",
                "payout_ratio": "0.5",
                "daily_limit": "100000",
                "source_doc": "약관",
                "source_page": "p.71",
                "source_clause": "상급병실료 차액",
                "source_chunk_id": "chunk-room",
                "approval_status": "active",
            }
        ],
    )

    registry = ClaimRuleRegistry.from_file(rules_path)
    rule = registry.lookup_special("upper_room_difference")

    assert rule.payout_ratio == Decimal("0.5")
    assert rule.daily_limit == Decimal("100000")
    assert rule.source_chunk_id == "chunk-room"
