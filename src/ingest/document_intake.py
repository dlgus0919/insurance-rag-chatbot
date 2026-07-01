"""Document type and text-layer checks for administrator knowledge intake."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from src.parser.pdf_parser import parse_pdf


class DocumentKind(StrEnum):
    PDF = "pdf"
    EXCEL = "excel"
    OCR_UNSUPPORTED = "ocr_unsupported"
    UNSUPPORTED = "unsupported"


class IntakeBlockReason(StrEnum):
    SCANNED_PDF_TEXT_LAYER_MISSING = "scanned_pdf_text_layer_missing"
    OCR_FILE_UNSUPPORTED = "ocr_file_unsupported"
    CANDIDATE_EXTRACTION_FAILED = "candidate_extraction_failed"
    SOURCE_FILE_MISSING = "source_file_missing"
    EXCEL_STAGING_NOT_READY = "excel_staging_not_ready"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"


EXCEL_SUFFIXES = {".xlsx", ".xls", ".csv"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
PDF_SUFFIXES = {".pdf"}

MIN_TEXT_CHARS_TOTAL = 200
MIN_TEXT_PAGE_RATIO = 0.5


@dataclass(frozen=True)
class PdfTextLayerReport:
    path: str
    page_count: int
    text_page_count: int
    total_text_chars: int
    text_page_ratio: float
    has_text_layer: bool
    block_reason: IntakeBlockReason | None
    user_message: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["block_reason"] = self.block_reason.value if self.block_reason else None
        return data


def classify_source_file(path: str | Path) -> DocumentKind:
    suffix = Path(path).suffix.lower()
    if suffix in PDF_SUFFIXES:
        return DocumentKind.PDF
    if suffix in EXCEL_SUFFIXES:
        return DocumentKind.EXCEL
    if suffix in IMAGE_SUFFIXES:
        return DocumentKind.OCR_UNSUPPORTED
    return DocumentKind.UNSUPPORTED


def evaluate_pdf_text_layer(path: str | Path) -> PdfTextLayerReport:
    source_path = Path(path)
    try:
        pages = parse_pdf(source_path)
    except Exception:
        pages = []
    page_count = len(pages)
    text_lengths = [len(str(text or "").strip()) for _, text in pages]
    text_page_count = sum(1 for length in text_lengths if length > 0)
    total_text_chars = sum(text_lengths)
    text_page_ratio = (text_page_count / page_count) if page_count else 0.0
    has_text_layer = total_text_chars >= MIN_TEXT_CHARS_TOTAL and text_page_ratio >= MIN_TEXT_PAGE_RATIO
    block_reason = None if has_text_layer else IntakeBlockReason.SCANNED_PDF_TEXT_LAYER_MISSING
    if has_text_layer:
        user_message = "디지털 PDF로 판정되었습니다. 텍스트 레이어 기반 후보 추출을 진행할 수 있습니다."
    else:
        user_message = (
            "이 PDF는 텍스트 레이어가 없거나 부족한 스캔본으로 보입니다. "
            "현재 시스템은 스캔 PDF OCR 자동화를 수행하지 않으므로 후보 추출과 DB 반영을 진행하지 않습니다. "
            "텍스트 레이어가 포함된 디지털 PDF 또는 Excel 파일을 추가해 주세요."
        )
    return PdfTextLayerReport(
        path=str(source_path),
        page_count=page_count,
        text_page_count=text_page_count,
        total_text_chars=total_text_chars,
        text_page_ratio=round(text_page_ratio, 4),
        has_text_layer=has_text_layer,
        block_reason=block_reason,
        user_message=user_message,
    )
