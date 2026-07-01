from __future__ import annotations

from pathlib import Path

import pytest

from src.api.routes import knowledge
from src.auth.users import User
from src.ingest.intake_store import IntakeJobStore, IntakeJobStatus


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _admin_user() -> User:
    return User(
        username="admin",
        password_hash="x",
        role="admin",
        display_name="관리자",
        created_at="2026-07-01T00:00:00+09:00",
        password_updated_at="2026-07-01T00:00:00+09:00",
        email=None,
        status="active",
        updated_at=None,
        last_login=None,
    )


@pytest.mark.anyio
async def test_list_intake_jobs_returns_runtime_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = IntakeJobStore(tmp_path)
    store.create_job(original_filename="약관.pdf", uploaded_by="admin", document_kind="pdf")
    monkeypatch.setattr(knowledge, "get_intake_store", lambda: store)

    payload = await knowledge.list_intake_jobs(_admin_user())

    assert payload["total"] == 1
    assert payload["items"][0]["original_filename"] == "약관.pdf"


@pytest.mark.anyio
async def test_list_intake_job_audit_returns_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")
    store.update_job(
        job.job_id,
        status=IntakeJobStatus.BLOCKED_SCANNED_PDF,
        message="텍스트 레이어가 없습니다.",
        block_reason="scanned_pdf_text_layer_missing",
        next_action="텍스트 레이어가 포함된 디지털 PDF를 업로드하세요.",
    )
    monkeypatch.setattr(knowledge, "get_intake_store", lambda: store)

    payload = await knowledge.list_intake_job_audit(job.job_id, _admin_user())

    assert payload["total"] == 2
    assert payload["items"][-1]["block_reason"] == "scanned_pdf_text_layer_missing"


@pytest.mark.anyio
async def test_run_intake_job_blocks_scanned_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")
    source = tmp_path / job.job_id / "source" / "scan.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4")
    store.update_job(job.job_id, status=IntakeJobStatus.UPLOADED, message="uploaded", source_path=str(source))
    monkeypatch.setattr(knowledge, "get_intake_store", lambda: store)
    monkeypatch.setattr(
        "src.ingest.intake_runner.evaluate_pdf_text_layer",
        lambda _path: type(
            "Report",
            (),
            {
                "has_text_layer": False,
                "block_reason": type("Reason", (), {"value": "scanned_pdf_text_layer_missing"})(),
                "user_message": "텍스트 레이어가 없습니다.",
                "as_dict": lambda self: {"has_text_layer": False, "block_reason": "scanned_pdf_text_layer_missing"},
            },
        )(),
    )

    payload = await knowledge.run_intake_job(job.job_id, _admin_user())

    assert payload["status"] == "blocked_scanned_pdf"
    assert "텍스트 레이어" in payload["message"]


@pytest.mark.anyio
async def test_list_rule_candidates_returns_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = tmp_path / "rule_candidates.jsonl"
    candidates.write_text(
        '{"candidate_id":"rulecand.demo","status":"pending","rule_type":"deductible","proposed_rule":{"rule_id":"demo","generation":"4th","category":"급여","visit_type":"outpatient","facility_grade":"all","copay_ratio":"0.2","min_deductible":"0","min_deductible_by_facility":{"clinic":"0","hospital":"0","general_hospital":"0","tertiary_hospital":"0"},"description":"demo","source_doc":"약관","source_page":"1","source_clause":"demo","source_chunk_id":"chunk:1","additional_source_refs":[],"source_status":"source_grounded","approval_status":"candidate"},"proposed_links":{"rule_id":"demo","source_refs":["chunk:1"],"ontology_refs":["cov.indemnity_medical"],"graph_refs":["source_chunk:chunk:1"],"link_status":"candidate"},"source_refs":[{"kind":"policy_chunk","chunk_id":"chunk:1"}],"evidence_text":"4세대 급여 통원 80% 보상"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(knowledge, "RULE_CANDIDATES_PATH", candidates)

    payload = await knowledge.list_rule_candidates(_admin_user())

    assert payload["total"] == 1
    assert payload["items"][0]["candidate_id"] == "rulecand.demo"


@pytest.mark.anyio
async def test_decide_rule_candidate_updates_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = tmp_path / "rule_candidates.jsonl"
    candidates.write_text(
        '{"candidate_id":"rulecand.demo","status":"pending","rule_type":"deductible","proposed_rule":{"rule_id":"demo","generation":"4th","category":"급여","visit_type":"outpatient","facility_grade":"all","copay_ratio":"0.2","min_deductible":"0","min_deductible_by_facility":{"clinic":"0","hospital":"0","general_hospital":"0","tertiary_hospital":"0"},"description":"demo","source_doc":"약관","source_page":"1","source_clause":"demo","source_chunk_id":"chunk:1","additional_source_refs":[],"source_status":"source_grounded","approval_status":"candidate"},"proposed_links":{"rule_id":"demo","source_refs":["chunk:1"],"ontology_refs":["cov.indemnity_medical"],"graph_refs":["source_chunk:chunk:1"],"link_status":"candidate"},"source_refs":[{"kind":"policy_chunk","chunk_id":"chunk:1"}],"evidence_text":"4세대 급여 통원 80% 보상"}\n',
        encoding="utf-8",
    )
    review_log = tmp_path / "review_log.jsonl"
    monkeypatch.setattr(knowledge, "RULE_CANDIDATES_PATH", candidates)
    monkeypatch.setattr(knowledge, "RULE_REVIEW_LOG_PATH", review_log)

    payload = await knowledge.decide_rule_candidate(
        "rulecand.demo",
        knowledge.CandidateDecisionRequest(decision="approve", reason="근거와 값이 일치합니다."),
        _admin_user(),
    )

    assert payload["status"] == "approved"


@pytest.mark.anyio
async def test_apply_approved_knowledge_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        knowledge,
        "apply_approved_knowledge",
        lambda: type("Result", (), {"as_dict": lambda self: {"status": "completed", "graph_rebuilt": True}})(),
    )

    payload = await knowledge.apply_approved(_admin_user())

    assert payload["status"] == "completed"
    assert payload["graph_rebuilt"] is True
