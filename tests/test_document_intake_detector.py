from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest.document_intake import (
    DocumentKind,
    IntakeBlockReason,
    classify_source_file,
    evaluate_pdf_text_layer,
)


def test_classify_source_file_accepts_digital_pdf_suffix() -> None:
    assert classify_source_file(Path("신규_약관.pdf")) == DocumentKind.PDF


def test_classify_source_file_accepts_excel_suffix() -> None:
    assert classify_source_file(Path("신규_요율.xlsx")) == DocumentKind.EXCEL


def test_classify_source_file_blocks_image_ocr() -> None:
    assert classify_source_file(Path("스캔본.jpg")) == DocumentKind.OCR_UNSUPPORTED


def test_pdf_text_layer_passes_when_pages_have_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.ingest.document_intake.parse_pdf",
        lambda _path: [(1, "약관 본문 " * 80), (2, "공제율 및 보상 비율 " * 60)],
    )

    report = evaluate_pdf_text_layer(Path("digital.pdf"))

    assert report.has_text_layer is True
    assert report.block_reason is None
    assert report.text_page_count == 2


def test_pdf_text_layer_blocks_scanned_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.ingest.document_intake.parse_pdf",
        lambda _path: [(1, ""), (2, "  "), (3, "")],
    )

    report = evaluate_pdf_text_layer(Path("scan.pdf"))

    assert report.has_text_layer is False
    assert report.block_reason == IntakeBlockReason.SCANNED_PDF_TEXT_LAYER_MISSING
    assert "텍스트 레이어" in report.user_message
