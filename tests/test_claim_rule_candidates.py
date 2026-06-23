from __future__ import annotations

import json

import pytest

from src.claim_calculation.rule_candidates import (
    CandidateValidationError,
    build_apply_plan,
    load_jsonl,
    validate_candidate_record,
    write_jsonl,
)


def _deductible_rule(**overrides):
    row = {
        "rule_id": "deductible.test.valid",
        "generation": "5th",
        "category": "급여",
        "visit_type": "outpatient",
        "facility_grade": "all",
        "copay_ratio": "0.2",
        "min_deductible": "0",
        "min_deductible_by_facility": {
            "clinic": "0",
            "hospital": "0",
            "general_hospital": "0",
            "tertiary_hospital": "0",
        },
        "per_visit_limit": None,
        "annual_limit": None,
        "annual_visit_limit": None,
        "description": "5세대 급여 통원: 본인부담금 20%",
        "source_doc": "약관",
        "source_page": "42",
        "source_clause": "보상하는 사항",
        "source_chunk_id": "test_chunk_001",
        "additional_source_refs": [],
        "source_status": "source_grounded",
        "approval_status": "candidate",
    }
    row.update(overrides)
    return row


def _candidate(**overrides):
    rule = overrides.pop("proposed_rule", _deductible_rule())
    rule_id = rule["rule_id"]
    row = {
        "candidate_id": f"rulecand.{rule_id}",
        "status": "pending",
        "rule_type": "deductible",
        "proposed_rule": rule,
        "proposed_links": {
            "rule_id": rule_id,
            "source_refs": ["policy_chunk:test_chunk_001"],
            "ontology_refs": ["cov.indemnity_medical"],
            "graph_refs": ["source_chunk:test_chunk_001"],
            "link_status": "candidate",
        },
        "source_refs": [{"kind": "policy_chunk", "chunk_id": "test_chunk_001"}],
        "evidence_text": "급여 본인부담금의 80%를 보상합니다.",
        "extraction_reason": "테스트 근거",
        "risk_flags": [],
        "created_at": "2026-06-23T00:00:00+09:00",
        "reviewed_at": None,
        "reviewer": None,
        "review_note": "",
    }
    row.update(overrides)
    return row


def test_candidate_requires_active_manifest_compatible_rule() -> None:
    validate_candidate_record(_candidate())


def test_candidate_rejects_missing_source_links() -> None:
    candidate = _candidate(source_refs=[], evidence_text="")

    with pytest.raises(CandidateValidationError, match="source"):
        validate_candidate_record(candidate)


def test_candidate_validates_prescription_rule() -> None:
    candidate = _candidate(
        rule_type="prescription",
        proposed_rule={
            "rule_id": "prescription.test",
            "generation": "5th",
            "deductible_amount": "8000",
            "per_visit_limit": "50000",
            "description": "처방조제 테스트",
            "source_doc": "약관",
            "source_page": "31",
            "source_clause": "제3조",
            "source_chunk_id": "chunk-rx",
            "approval_status": "candidate",
            "source_status": "source_grounded",
        },
    )
    candidate["proposed_links"]["rule_id"] = "prescription.test"

    validate_candidate_record(candidate)


def test_candidate_validates_special_rule() -> None:
    candidate = _candidate(
        rule_type="special",
        proposed_rule={
            "rule_id": "special.test",
            "special_type": "upper_room_difference",
            "payout_ratio": "0.5",
            "daily_limit": "100000",
            "description": "특례 테스트",
            "source_doc": "약관",
            "source_page": "71",
            "source_clause": "상급병실료 차액",
            "source_chunk_id": "chunk-room",
            "approval_status": "candidate",
            "source_status": "source_grounded",
        },
    )
    candidate["proposed_links"]["rule_id"] = "special.test"

    validate_candidate_record(candidate)


def test_apply_plan_merges_only_approved_candidates() -> None:
    approved = _candidate(status="approved", reviewed_at="2026-06-23T00:01:00+09:00", reviewer="tester")
    pending = _candidate(
        proposed_rule=_deductible_rule(rule_id="deductible.test.pending", source_chunk_id="test_chunk_002"),
    )

    plan = build_apply_plan(active_rules=[{"rule_id": "deductible.existing"}], active_links=[], candidates=[approved, pending])

    assert [rule["rule_id"] for rule in plan.rules_to_add] == ["deductible.test.valid"]
    assert plan.rules_to_add[0]["approval_status"] == "active"
    assert [link["rule_id"] for link in plan.links_to_add] == ["deductible.test.valid"]
    assert plan.links_to_add[0]["link_status"] == "active"
    assert plan.applied_candidate_ids == ["rulecand.deductible.test.valid"]


def test_apply_plan_blocks_duplicate_rule_id() -> None:
    candidate = _candidate(status="approved")

    with pytest.raises(CandidateValidationError, match="duplicate"):
        build_apply_plan(active_rules=[{"rule_id": "deductible.test.valid"}], active_links=[], candidates=[candidate])


def test_jsonl_roundtrip(tmp_path) -> None:
    path = tmp_path / "candidates.jsonl"
    record = _candidate()

    write_jsonl(path, [record])

    assert load_jsonl(path) == [json.loads(path.read_text(encoding="utf-8"))]
