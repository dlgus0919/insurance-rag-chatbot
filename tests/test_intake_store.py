from __future__ import annotations

from pathlib import Path

from src.ingest.intake_store import IntakeJobStore, IntakeJobStatus


def test_create_job_writes_runtime_job_json(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)

    job = store.create_job(original_filename="약관.pdf", uploaded_by="admin", document_kind="pdf")

    assert job.job_id.startswith("intake_")
    assert job.status == IntakeJobStatus.UPLOADED
    assert (tmp_path / job.job_id / "job.json").exists()


def test_create_job_appends_initial_audit_event(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)

    job = store.create_job(original_filename="약관.pdf", uploaded_by="admin", document_kind="pdf")

    events = store.load_audit_events(job.job_id)
    assert len(events) == 1
    assert events[0]["actor"] == "admin"
    assert events[0]["from_status"] is None
    assert events[0]["to_status"] == "uploaded"
    assert events[0]["event_type"] == "status_changed"


def test_update_status_persists_block_reason(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")

    updated = store.update_job(
        job.job_id,
        status=IntakeJobStatus.BLOCKED_SCANNED_PDF,
        message="텍스트 레이어가 없습니다.",
        details={"block_reason": "scanned_pdf_text_layer_missing"},
    )

    loaded = store.load_job(job.job_id)
    assert updated.status == IntakeJobStatus.BLOCKED_SCANNED_PDF
    assert loaded.status == IntakeJobStatus.BLOCKED_SCANNED_PDF
    assert loaded.message == "텍스트 레이어가 없습니다."
    assert loaded.details["block_reason"] == "scanned_pdf_text_layer_missing"


def test_update_job_appends_blocked_audit_event(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")

    store.update_job(
        job.job_id,
        status=IntakeJobStatus.BLOCKED_SCANNED_PDF,
        message="텍스트 레이어가 없습니다.",
        block_reason="scanned_pdf_text_layer_missing",
        next_action="텍스트 레이어가 포함된 디지털 PDF를 업로드하세요.",
        details={"text_page_count": 0},
    )

    events = store.load_audit_events(job.job_id)
    assert [event["to_status"] for event in events] == ["uploaded", "blocked_scanned_pdf"]
    assert events[-1]["event_type"] == "blocked"
    assert events[-1]["block_reason"] == "scanned_pdf_text_layer_missing"
    assert "디지털 PDF" in events[-1]["next_action"]
    assert events[-1]["details"]["text_page_count"] == 0


def test_list_jobs_returns_newest_first(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    first = store.create_job(original_filename="a.pdf", uploaded_by="admin", document_kind="pdf")
    second = store.create_job(original_filename="b.pdf", uploaded_by="admin", document_kind="pdf")

    jobs = store.list_jobs()

    assert [job.job_id for job in jobs] == [second.job_id, first.job_id]
