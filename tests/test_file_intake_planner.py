from __future__ import annotations

from src.ingest.file_intake_planner import plan_file_intake


def test_excel_intake_plan_is_blocked_until_staging_ready():
    plan = plan_file_intake("신규_비급여.xlsx")

    assert plan.file_type == "excel"
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is False
    assert plan.steps == ["excel_staging_not_ready"]


def test_pdf_intake_plan_detects_text_layer_before_pipeline_choice():
    plan = plan_file_intake("신규_약관.pdf")

    assert plan.file_type == "pdf"
    assert plan.steps[:3] == [
        "detect_pdf_text_layer",
        "block_if_scanned_pdf",
        "choose_digital_pdf_pipeline",
    ]
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is True


def test_image_intake_plan_blocks_ocr_auto_run():
    plan = plan_file_intake("영수증.jpg")

    assert plan.file_type == "ocr_unsupported"
    assert "block_ocr_required" in plan.steps
    assert "run_scanned_document_ocr" not in plan.steps
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is False


def test_unsupported_intake_plan_rejects_without_mutation_or_approval():
    plan = plan_file_intake("notes.txt")

    assert plan.file_type == "unsupported"
    assert plan.steps == ["reject_unsupported_file"]
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is False
