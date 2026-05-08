from pathlib import Path

from PIL import Image

import scripts.ocr_extract as ocr_extract
from src.parser.ocr_engine import LayoutBlock


def test_parse_pages_arg_supports_ranges_and_lists() -> None:
    assert ocr_extract.parse_pages_arg("60-62,70", total_pages=100) == [60, 61, 62, 70]


def test_process_page_writes_structured_outputs(monkeypatch, tmp_path: Path) -> None:
    image = Image.new("RGB", (200, 200), color="white")
    table_html = """
    <table>
      <tr><td>수술종수</td><td>수술명</td><td>수술해설</td></tr>
      <tr><td>1종</td><td>반월판연골 봉합술</td><td>봉합하는 수술</td></tr>
    </table>
    """

    monkeypatch.setattr(ocr_extract, "extract_page_image", lambda _pdf, _page: image)
    monkeypatch.setattr(
        ocr_extract,
        "run_ppstructure",
        lambda _image: [
            LayoutBlock("text", [0, 0, 100, 20], "수술올 말하다", confidence=0.9),
            LayoutBlock("table", [0, 20, 180, 100], "수술종수 | 수술명 | 수술해설", html=table_html, confidence=0.95),
            LayoutBlock("figure", [10, 110, 80, 180], "", confidence=1.0),
        ],
    )

    page_meta = ocr_extract.process_page(tmp_path / "dummy.pdf", 66, tmp_path / "out")

    assert page_meta["engine"] == "ppstructure"
    assert [block["type"] for block in page_meta["blocks"]] == ["text", "table", "figure"]
    assert (tmp_path / "out" / "text" / "p066_b00.txt").read_text(encoding="utf-8") == "수술을 말하다"
    assert (tmp_path / "out" / "tables" / "p066_t00.json").exists()
    assert (tmp_path / "out" / "images" / "p066_f00.jpg").exists()


def test_process_page_falls_back_to_easyocr(monkeypatch, tmp_path: Path) -> None:
    image = Image.new("RGB", (100, 100), color="white")
    monkeypatch.setattr(ocr_extract, "extract_page_image", lambda _pdf, _page: image)
    monkeypatch.setattr(ocr_extract, "run_ppstructure", lambda _image: [])
    monkeypatch.setattr(
        ocr_extract,
        "run_easyocr_fallback",
        lambda _image: [LayoutBlock("text", [0, 0, 80, 20], "폴백 텍스트", confidence=0.8)],
    )

    page_meta = ocr_extract.process_page(tmp_path / "dummy.pdf", 1, tmp_path / "out")

    assert page_meta["engine"] == "easyocr"
    assert page_meta["fallback_reason"] == "ppstructure_low_confidence_below_0.5"
