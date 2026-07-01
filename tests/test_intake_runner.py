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
    events = store.load_audit_events(job.job_id)
    assert events[-1]["block_reason"] == "ocr_file_unsupported"
    assert "디지털 PDF" in events[-1]["next_action"]


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
    events = store.load_audit_events(job.job_id)
    assert events[-1]["block_reason"] == "scanned_pdf_text_layer_missing"
    assert "텍스트 레이어" in events[-1]["next_action"]


def test_runner_logs_candidate_extraction_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr("src.ingest.intake_runner.parse_pdf", lambda _path: [(1, "본문")])
    monkeypatch.setattr("src.ingest.intake_runner._write_candidate_outputs", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.FAILED
    events = store.load_audit_events(job.job_id)
    assert events[-1]["block_reason"] == "candidate_extraction_failed"
    assert events[-1]["details"]["error_type"] == "RuntimeError"


def test_runner_fails_pdf_with_missing_source_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="missing.pdf", uploaded_by="admin", document_kind="pdf")
    monkeypatch.setattr(
        "src.ingest.intake_runner.evaluate_pdf_text_layer",
        lambda _path: pytest.fail("missing source_path must fail before text-layer evaluation"),
    )

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.FAILED
    events = store.load_audit_events(job.job_id)
    assert events[-1]["block_reason"] == "source_file_missing"
    assert "다시 업로드" in events[-1]["next_action"]


def test_runner_logs_excel_staging_not_ready(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="rules.xlsx", uploaded_by="admin", document_kind="excel")

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.FAILED
    events = store.load_audit_events(job.job_id)
    assert events[-1]["block_reason"] == "excel_staging_not_ready"
    assert "Excel staging" in events[-1]["next_action"]


def test_runner_logs_unsupported_kind_reason(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="notes.txt", uploaded_by="admin", document_kind="unsupported")

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.BLOCKED_UNSUPPORTED
    events = store.load_audit_events(job.job_id)
    assert events[-1]["block_reason"] == "unsupported_file_type"
    assert "디지털 PDF" in events[-1]["next_action"]


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
    monkeypatch.setattr(
        "src.ingest.intake_runner._write_candidate_outputs",
        lambda job_dir, _chunks_path, _job_id: {
            "ontology_candidates_path": str(job_dir / "review" / "ontology_candidates.jsonl"),
            "rule_candidates_path": str(job_dir / "review" / "rule_candidates.jsonl"),
            "ontology_candidate_count": 1,
            "rule_candidate_count": 1,
            "ontology_warnings": [],
        },
    )

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.WAITING_REVIEW
    chunks_path = Path(result.staging_chunks_path or "")
    rows = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["text"] == "4세대 급여 통원 80% 보상"
    assert rows[0]["metadata"]["doc_short"].startswith("intake_")
    assert result.details["ontology_candidates_path"].endswith("ontology_candidates.jsonl")
    assert result.details["rule_candidates_path"].endswith("rule_candidates.jsonl")
