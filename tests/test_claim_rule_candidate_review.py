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


def test_generic_extractor_distinguishes_copay_and_payout_semantics() -> None:
    from scripts.extract_claim_rule_candidates import extract_candidates_from_text

    copay_candidate = extract_candidates_from_text(
        text="4세대 비급여 통원 본인부담금 30%를 공제합니다.",
        doc_short="약관",
        chunk_id="약관_ch_test_copay",
        page=1,
        article="제3조",
    )[0]
    payout_candidate = extract_candidates_from_text(
        text="4세대 비급여 통원 의료비의 80%를 보상합니다.",
        doc_short="약관",
        chunk_id="약관_ch_test_payout",
        page=1,
        article="제3조",
    )[0]

    assert copay_candidate["proposed_rule"]["copay_ratio"] == "0.3"
    assert payout_candidate["proposed_rule"]["copay_ratio"] == "0.2"


def test_generic_extractor_skips_ambiguous_percentage_meaning() -> None:
    from scripts.extract_claim_rule_candidates import extract_candidates_from_text

    candidates = extract_candidates_from_text(
        text="4세대 비급여 통원 관련 비율은 30%입니다.",
        doc_short="약관",
        chunk_id="약관_ch_test_ambiguous",
        page=1,
        article="제3조",
    )

    assert candidates == []


def test_fourth_manual_therapy_extractor_creates_review_only_candidates() -> None:
    from scripts.extract_claim_rule_candidates import extract_fourth_manual_therapy_candidates

    chunks = [
        {
            "text": "도수치료, 체외충격파치료 및 증식치료는 보장대상의료비의 30%와 3만원 중 큰 금액을 공제합니다. 2022.4",
            "doc_short": "약관",
            "chunk_id": "약관_ch_002441",
            "page": "71-78",
            "article": "제3조 보장종목별 보상내용 / 3대비급여 특별약관",
        },
        {
            "text": "만원 최초 10회부터 증상 호전 여부를 확인할 수 있는 증빙이 필요하며 연간 350만원, 50회를 한도로 합니다.",
            "doc_short": "약관",
            "chunk_id": "약관_ch_002442",
            "page": "71-78",
            "article": "제3조",
        },
        {
            "text": "동일한 날 여러 번 시행한 치료는 1회로 봅니다.",
            "doc_short": "약관",
            "chunk_id": "약관_ch_002443",
            "page": "71-78",
            "article": "제3조",
        },
    ]

    candidates = extract_fourth_manual_therapy_candidates(chunks)

    assert {candidate["proposed_rule"]["rule_id"] for candidate in candidates} == {
        "deductible.4th.three_major_manual.hospitalization",
        "deductible.4th.three_major_manual.outpatient",
    }
    assert all(candidate["status"] == "pending" for candidate in candidates)
    assert all(candidate["proposed_rule"]["approval_status"] == "candidate" for candidate in candidates)
    assert all(candidate["proposed_rule"]["copay_ratio"] == "0.3" for candidate in candidates)
    assert all(candidate["proposed_rule"]["annual_limit"] == "3500000" for candidate in candidates)
    assert all(candidate["proposed_rule"]["annual_visit_limit"] == 50 for candidate in candidates)
    assert all(candidate["proposed_rule"]["additional_source_refs"] == ["약관_ch_002442", "약관_ch_002443"] for candidate in candidates)


def test_iter_policy_chunks_prefers_source_chunk_id_for_canonical_provenance(tmp_path: Path) -> None:
    from scripts.extract_claim_rule_candidates import iter_policy_chunks

    index = tmp_path / "chunks.jsonl"
    index.write_text(
        json.dumps(
            {
                "id": "약관_v1_ch_002441",
                "text": "4세대 도수치료 근거",
                "metadata": {
                    "source_chunk_id": "약관_ch_002441",
                    "doc_short": "약관",
                    "page_start": 71,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    chunks = iter_policy_chunks(index)

    assert chunks[0]["chunk_id"] == "약관_ch_002441"
    assert chunks[0]["page"] == 71
