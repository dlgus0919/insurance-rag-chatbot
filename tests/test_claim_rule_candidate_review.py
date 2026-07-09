from __future__ import annotations

import json
import runpy
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


def test_apply_replaces_active_rule_and_link(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    review_log = tmp_path / "review_log.jsonl"
    rules = tmp_path / "rules.json"
    links = tmp_path / "links.json"
    candidate = _candidate()
    candidate["status"] = "approved"
    candidate["operation"] = "replace"
    candidate["target_rule_id"] = "deductible.test.cli"
    active_rule = dict(candidate["proposed_rule"], copay_ratio="0.5", approval_status="active")
    _write_jsonl(candidates, candidate)
    rules.write_text(
        json.dumps({"version": 1, "rules": [active_rule], "prescription_rules": [], "special_rules": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    links.write_text(
        json.dumps([{"rule_id": "deductible.test.cli", "source_refs": ["policy_chunk:old"], "link_status": "active"}], ensure_ascii=False),
        encoding="utf-8",
    )

    subprocess.run(
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
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    updated_rule = json.loads(rules.read_text(encoding="utf-8"))["rules"][0]
    updated_link = json.loads(links.read_text(encoding="utf-8"))[0]
    updated_candidate = json.loads(candidates.read_text(encoding="utf-8"))
    assert updated_rule["copay_ratio"] == "0.2"
    assert updated_rule["approval_status"] == "active"
    assert updated_link["source_refs"] == ["policy_chunk:chunk-1"]
    assert updated_link["link_status"] == "active"
    assert updated_candidate["status"] == "applied"


def test_gui_dry_run_prints_candidate_preview(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    review_log = tmp_path / "review_log.jsonl"
    _write_jsonl(candidates, _candidate())

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--candidates",
            str(candidates),
            "--review-log",
            str(review_log),
            "--gui",
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "candidate_count=1" in result.stdout
    assert "후보 ID: rulecand.test.cli" in result.stdout
    assert "구분: 신규 룰 후보 5세대 급여 통원 전체 의료기관" in result.stdout


def test_candidate_description_uses_practitioner_labels() -> None:
    namespace = runpy.run_path(str(SCRIPT))

    assert namespace["candidate_description"](_candidate()) == "신규 룰 후보 5세대 급여 통원 전체 의료기관: 본인부담금 20%"


def test_gui_dry_run_uses_practitioner_labels_for_unknown_fields(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    review_log = tmp_path / "review_log.jsonl"
    candidate = _candidate()
    candidate["proposed_rule"]["category"] = "unknown"
    candidate["proposed_rule"]["visit_type"] = "unknown"
    _write_jsonl(candidates, candidate)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--candidates",
            str(candidates),
            "--review-log",
            str(review_log),
            "--gui",
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "구분: 신규 룰 후보 5세대 급여/비급여 미확정 입원/통원 미확정 전체 의료기관" in result.stdout
    assert "outpatient" not in result.stdout


def test_special_case_5th_extractor_builds_practitioner_named_candidates() -> None:
    from scripts.claim_rule_candidate_review import candidate_summary
    from scripts.extract_claim_rule_candidates import extract_special_case_5th_candidates

    chunks = [
        {
            "text": "5세대 산정특례 적용 대상자의 3대비급여는 본인부담금 30%를 공제한다.",
            "doc_short": "표준약관",
            "chunk_id": "표준약관_ch_005607",
            "page": 1,
            "article": "5세대 산정특례",
        },
        {
            "text": "산정특례 미적용 MRI MRA 자기공명영상진단은 비급여 자기공명영상진단으로 본인부담금 50%를 공제한다.",
            "doc_short": "표준약관",
            "chunk_id": "표준약관_ch_005628",
            "page": 2,
            "article": "자기공명영상진단",
        },
    ]

    candidates = extract_special_case_5th_candidates(chunks)

    assert len(candidates) >= 2
    summaries = [candidate_summary(candidate) for candidate in candidates]
    assert any("산정특례 적용" in summary for summary in summaries)
    assert any("비급여 MRI/MRA" in summary for summary in summaries)
    assert all("unknown" not in summary for summary in summaries)
