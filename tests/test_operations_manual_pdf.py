from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md"
SCRIPT = ROOT / "scripts/build_operations_manual_pdf.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("operations_manual_pdf", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operations_manual_pdf_contains_title_ids_and_page_numbers() -> None:
    builder = _load_builder()
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "manual.pdf"
        builder.build_pdf(MANUAL, output, builder.resolve_korean_font())

        reader = PdfReader(str(output))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert len(reader.pages) >= 2
    assert "실무자 전체 운영 오류 대응 매뉴얼" in text
    assert "AUTH-001" in text
    assert "SYSTEM-003" in text
    assert "페이지 1" in text


def test_operations_manual_pdf_uses_korean_cid_font_for_ttc_input() -> None:
    builder = _load_builder()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        ttc_font = temp_path / "NotoSansCJK-Regular.ttc"
        ttc_font.touch()
        output = temp_path / "manual.pdf"
        builder.build_pdf(MANUAL, output, ttc_font)

        reader = PdfReader(str(output))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "실무자 전체 운영 오류 대응 매뉴얼" in text
    assert "페이지 1" in text


if __name__ == "__main__":
    test_operations_manual_pdf_contains_title_ids_and_page_numbers()
    print("operations manual PDF checks passed")
