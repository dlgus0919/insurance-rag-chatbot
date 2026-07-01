from __future__ import annotations

from pathlib import Path

from src.ingest.intake_store import IntakeJobStore, IntakeJobStatus


def test_create_job_writes_runtime_job_json(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)

    job = store.create_job(original_filename="약관.pdf", uploaded_by="admin", document_kind="pdf")

    assert job.job_id.startswith("intake_")
    assert job.status == IntakeJobStatus.UPLOADED
    assert (tmp_path / job.job_id / "job.json").exists()


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


def test_list_jobs_returns_newest_first(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    first = store.create_job(original_filename="a.pdf", uploaded_by="admin", document_kind="pdf")
    second = store.create_job(original_filename="b.pdf", uploaded_by="admin", document_kind="pdf")

    jobs = store.list_jobs()

    assert [job.job_id for job in jobs] == [second.job_id, first.job_id]
