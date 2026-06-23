from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path("scripts/claim_rule_candidate_review.py")


def _candidate() -> dict:
    return {
        "candidate_id": "rulecand.test.cli",
        "status": "pending",
        "rule_type": "deductible",
        "proposed_rule": {
            "rule_id": "deductible.test.cli",
            "generation": "5th",
            "category": "급여",
            "visit_type": "outpatient",
            "facility_grade": "all",
            "copay_ratio": "0.2",
            "min_deductible": "0",
            "min_deductible_by_facility": {},
            "per_visit_limit": None,
            "annual_limit": None,
            "annual_visit_limit": None,
            "description": "test",
            "source_doc": "약관",
            "source_page": "1",
            "source_clause": "제1조",
            "source_chunk_id": "chunk-1",
            "approval_status": "candidate",
            "source_status": "source_grounded",
        },
        "proposed_links": {
            "rule_id": "deductible.test.cli",
            "source_refs": ["policy_chunk:chunk-1"],
            "ontology_refs": ["cov.indemnity_medical"],
            "graph_refs": ["source_chunk:chunk-1"],
            "link_status": "candidate",
        },
        "source_refs": [{"kind": "policy_chunk", "chunk_id": "chunk-1"}],
        "evidence_text": "급여 본인부담금의 80%를 보상합니다.",
        "extraction_reason": "테스트",
        "risk_flags": [],
        "created_at": "2026-06-23T00:00:00+09:00",
        "reviewed_at": None,
        "reviewer": None,
        "review_note": "",
    }


def _write_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")


def test_list_json_and_decide(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    review_log = tmp_path / "review_log.jsonl"
    _write_jsonl(candidates, _candidate())

    listed = subprocess.run([sys.executable, str(SCRIPT), "--candidates", str(candidates), "--review-log", str(review_log), "--list-json"], check=True, text=True, capture_output=True)
    assert "rulecand.test.cli" in listed.stdout

    decided = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--candidates",
            str(candidates),
            "--review-log",
            str(review_log),
            "--decide",
            "rulecand.test.cli",
            "--decision",
            "approve",
            "--reviewer",
            "tester",
            "--reason",
            "근거 확인",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "approved" in decided.stdout
    assert "rulecand.test.cli" in review_log.read_text(encoding="utf-8")


def test_apply_dry_run_does_not_write_active_manifest(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    review_log = tmp_path / "review_log.jsonl"
    rules = tmp_path / "rules.json"
    links = tmp_path / "links.json"
    candidate = _candidate()
    candidate["status"] = "approved"
    _write_jsonl(candidates, candidate)
    rules.write_text(json.dumps({"version": 1, "rules": [], "prescription_rules": [], "special_rules": []}, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--candidates",
            str(candidates),
            "--review-log",
            str(review_log),
            "--rules-path",
            str(rules),
            "--links-path",
            str(links),
            "--apply",
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "deductible.test.cli" in result.stdout
    assert json.loads(rules.read_text(encoding="utf-8"))["rules"] == []
    assert not links.exists()
