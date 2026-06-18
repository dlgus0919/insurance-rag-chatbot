from __future__ import annotations

from src.ingest.file_intake_planner import plan_file_intake


def test_excel_intake_plan_waits_for_practitioner_approval():
    plan = plan_file_intake("신규_비급여.xlsx")

    assert plan.file_type == "excel"
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is True
    assert "extract_rows" in plan.steps
    assert "ontology_candidates_pending" in plan.steps
    assert plan.steps[-1] == "wait_for_practitioner_approval"


def test_pdf_intake_plan_detects_text_layer_before_pipeline_choice():
    plan = plan_file_intake("신규_약관.pdf")

    assert plan.file_type == "pdf"
    assert plan.steps[:2] == ["detect_pdf_text_layer", "choose_digital_or_scanned_pipeline"]
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is True


def test_image_intake_plan_uses_scanned_ocr_gate():
    plan = plan_file_intake("영수증.jpg")

    assert plan.file_type == "image"
    assert "run_scanned_document_ocr" in plan.steps
    assert "wait_for_practitioner_approval" in plan.steps


def test_unsupported_intake_plan_rejects_without_mutation_or_approval():
    plan = plan_file_intake("notes.txt")

    assert plan.file_type == "unsupported"
    assert plan.steps == ["reject_unsupported_file"]
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is False
