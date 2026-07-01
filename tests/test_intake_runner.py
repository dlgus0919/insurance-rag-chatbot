from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingest.intake_runner import run_intake_job_once
from src.ingest.intake_store import IntakeJobStore, IntakeJobStatus


def test_runner_blocks_ocr_unsupported_image(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.jpg", uploaded_by="admin", document_kind="ocr_unsupported")

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.BLOCKED_UNSUPPORTED
    assert "OCR 자동화" in result.message


def test_runner_blocks_scanned_pdf_before_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")
    source = store.job_dir(job.job_id) / "source" / "scan.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4")
    store.update_job(job.job_id, status=IntakeJobStatus.UPLOADED, message="uploaded", source_path=str(source))
    monkeypatch.setattr(
        "src.ingest.intake_runner.evaluate_pdf_text_layer",
        lambda _path: type(
            "Report",
            (),
            {
                "has_text_layer": False,
                "block_reason": type("Reason", (), {"value": "scanned_pdf_text_layer_missing"})(),
                "user_message": "텍스트 레이어가 없습니다.",
                "as_dict": lambda self: {"has_text_layer": False},
            },
        )(),
    )

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.BLOCKED_SCANNED_PDF
    assert not (store.job_dir(job.job_id) / "staging" / "chunks.jsonl").exists()


def test_runner_writes_staging_chunks_and_candidate_outputs_for_digital_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="digital.pdf", uploaded_by="admin", document_kind="pdf")
    source = store.job_dir(job.job_id) / "source" / "digital.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4")
    store.update_job(job.job_id, status=IntakeJobStatus.UPLOADED, message="uploaded", source_path=str(source))
    monkeypatch.setattr(
        "src.ingest.intake_runner.evaluate_pdf_text_layer",
        lambda _path: type(
            "Report",
            (),
            {
                "has_text_layer": True,
                "block_reason": None,
                "user_message": "디지털 PDF입니다.",
                "as_dict": lambda self: {"has_text_layer": True},
            },
        )(),
    )
    monkeypatch.setattr("src.ingest.intake_runner.parse_pdf", lambda _path: [(1, "4세대 급여 통원 80% 보상")])

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.WAITING_REVIEW
    chunks_path = Path(result.staging_chunks_path or "")
    rows = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["text"] == "4세대 급여 통원 80% 보상"
    assert rows[0]["metadata"]["doc_short"].startswith("intake_")
    assert result.details["ontology_candidates_path"].endswith("ontology_candidates.jsonl")
    assert result.details["rule_candidates_path"].endswith("rule_candidates.jsonl")
