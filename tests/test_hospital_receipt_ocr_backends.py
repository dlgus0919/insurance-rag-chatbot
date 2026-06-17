from __future__ import annotations

from PIL import Image

from src.hospital_receipt_ocr.backends.opencv_paddle import OcrTextBox
from src.hospital_receipt_ocr.backends.ppstructure import extract_tables_from_image as extract_ppstructure_tables
from src.hospital_receipt_ocr.backends.surya import SuryaAdapter, _collect_table_items, extract_tables_from_image as extract_surya_tables
from src.hospital_receipt_ocr.backends.tatr_ocr import TatrOcrAdapter, extract_tables_from_image as extract_tatr_tables
from src.hospital_receipt_ocr.backends.table_html import html_table_to_ocr_table, parse_table_html


def test_table_html_parser_expands_simple_rows_and_colspan() -> None:
    rows = parse_table_html("<table><tr><th>코드</th><th colspan='2'>금액</th></tr><tr><td>L1213</td><td>117,170</td><td>117,170</td></tr></table>")

    assert rows == [["코드", "금액", ""], ["L1213", "117,170", "117,170"]]


def test_html_table_to_ocr_table_uses_common_contract() -> None:
    table = html_table_to_ocr_table(
        page_id="p001",
        table_id="p001_pp_t001",
        bbox=[10, 20, 110, 80],
        html="<table><tr><td>코드</td><td>명칭</td></tr><tr><td>L1213</td><td>척추마취관리기본</td></tr></table>",
        source_method="ppstructure",
        raw={"backend": "test"},
    )

    assert table is not None
    assert table.rows == 2
    assert table.cols == 2
    assert table.cells[0].source_method == "ppstructure"
    assert table.cells[3].text == "척추마취관리기본"
    assert table.cells[3].raw["backend"] == "test"


def test_ppstructure_backend_converts_table_html_region() -> None:
    image = Image.new("RGB", (200, 100), "white")

    class FakePPStructure:
        unavailable_reason = ""

        def structure_image(self, _image):
            return [
                {
                    "type": "table",
                    "bbox": [0, 0, 200, 100],
                    "res": {
                        "html": "<table><tr><td>코드</td><td>총액</td></tr><tr><td>L1213</td><td>117,170</td></tr></table>"
                    },
                }
            ]

    tables = extract_ppstructure_tables(image, page_id="p001", ppstructure=FakePPStructure())

    assert len(tables) == 1
    assert tables[0].table_id == "p001_pp_t001"
    assert tables[0].cells[2].text == "L1213"
    assert tables[0].cells[3].text == "117,170"


def test_ppstructure_backend_prefers_cell_bbox_with_korean_ocr_assignment() -> None:
    image = Image.new("RGB", (200, 100), "white")

    class FakePPStructure:
        unavailable_reason = ""

        def structure_image(self, _image):
            return [
                {
                    "type": "table",
                    "bbox": [0, 0, 200, 100],
                    "res": {
                        "cell_bbox": [
                            [0, 0, 100, 40],
                            [100, 0, 200, 40],
                            [0, 40, 100, 80],
                            [100, 40, 200, 80],
                        ],
                        "html": "<table><tr><td>bad</td><td>bad</td></tr></table>",
                    },
                }
            ]

    class FakeOcr:
        def ocr_image(self, _image):
            return [
                OcrTextBox([10, 10, 40, 20], "코드", 0.99),
                OcrTextBox([110, 10, 150, 20], "총액", 0.99),
                OcrTextBox([10, 50, 40, 60], "L1213", 0.99),
                OcrTextBox([110, 50, 160, 60], "117,170", 0.99),
            ]

    tables = extract_ppstructure_tables(image, page_id="p001", ppstructure=FakePPStructure(), text_ocr=FakeOcr())

    assert len(tables) == 1
    assert tables[0].cells[0].source_method == "ppstructure_korean_ocr"
    assert [cell.text for cell in tables[0].cells] == ["코드", "총액", "L1213", "117,170"]


def test_surya_backend_degrades_without_explicit_inference() -> None:
    image = Image.new("RGB", (100, 50), "white")
    adapter = SuryaAdapter()

    tables = extract_surya_tables(image, page_id="p001", surya=adapter)

    assert tables == []
    assert "disabled" in adapter.unavailable_reason


def test_surya_collects_table_rec_full_html_with_bbox() -> None:
    image = Image.new("RGB", (200, 100), "white")

    class FakeTableResult:
        html = "<table><tr><td>코드</td><td>총액</td></tr><tr><td>L1213</td><td>117,170</td></tr></table>"
        image_bbox = [10, 20, 180, 90]

    items = _collect_table_items([FakeTableResult()], image=image)

    assert len(items) == 1
    assert items[0]["source"] == "table_rec_full"
    assert items[0]["bbox"] == [10, 20, 180, 90]
    assert "L1213" in items[0]["html"]


def test_tatr_backend_intersects_rows_columns_and_assigns_ocr() -> None:
    image = Image.new("RGB", (200, 120), "white")

    class FakeTatr(TatrOcrAdapter):
        def _table_boxes(self, _image):
            return [[0, 0, 200, 120]]

        def _predict(self, _image, model_name):
            if "structure" not in model_name:
                return []
            return [
                {"label": "table row", "bbox": [0, 0, 200, 40]},
                {"label": "table row", "bbox": [0, 40, 200, 80]},
                {"label": "table column", "bbox": [0, 0, 100, 120]},
                {"label": "table column", "bbox": [100, 0, 200, 120]},
            ]

    class FakeOcr:
        def ocr_image(self, _image):
            return [
                OcrTextBox([10, 10, 30, 20], "코드", 0.9),
                OcrTextBox([110, 10, 140, 20], "총액", 0.9),
                OcrTextBox([10, 50, 40, 60], "L1213", 0.9),
                OcrTextBox([110, 50, 160, 60], "117,170", 0.9),
            ]

    adapter = FakeTatr()
    tables = extract_tatr_tables(image, page_id="p001", tatr=adapter, text_ocr=FakeOcr())

    assert len(tables) == 1
    assert tables[0].rows == 2
    assert tables[0].cols == 2
    assert [cell.text for cell in tables[0].cells] == ["코드", "총액", "L1213", "117,170"]
    assert "코드" in adapter.last_page_text
