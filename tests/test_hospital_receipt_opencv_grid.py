from __future__ import annotations

from PIL import Image, ImageDraw

from src.hospital_receipt_ocr.backends.opencv_paddle import OcrTextBox, build_cells, detect_grid_lines, extract_tables_from_image
from src.hospital_receipt_ocr.normalize import normalize_detail_rows


class FakeOcr:
    def ocr_image(self, _image: Image.Image) -> list[OcrTextBox]:
        return [
            OcrTextBox([5, 5, 25, 20], "항목", 0.99),
            OcrTextBox([45, 5, 65, 20], "일자", 0.99),
            OcrTextBox([85, 5, 105, 20], "코드", 0.99),
            OcrTextBox([125, 5, 155, 20], "명칭", 0.99),
            OcrTextBox([165, 5, 195, 20], "금액", 0.99),
            OcrTextBox([205, 5, 225, 20], "횟수", 0.99),
            OcrTextBox([245, 5, 265, 20], "일수", 0.99),
            OcrTextBox([285, 5, 315, 20], "총액", 0.99),
            OcrTextBox([325, 5, 355, 20], "본인", 0.99),
            OcrTextBox([365, 5, 395, 20], "공단", 0.99),
            OcrTextBox([405, 5, 435, 20], "전액", 0.99),
            OcrTextBox([445, 5, 475, 20], "비급여", 0.99),
            OcrTextBox([5, 45, 25, 60], "마취료", 0.99),
            OcrTextBox([45, 45, 75, 60], "20260325", 0.99),
            OcrTextBox([85, 45, 115, 60], "L1213", 0.99),
            OcrTextBox([125, 45, 155, 60], "척추마취", 0.99),
            OcrTextBox([165, 45, 195, 60], "117,170", 0.99),
            OcrTextBox([205, 45, 225, 60], "1", 0.99),
            OcrTextBox([245, 45, 265, 60], "1", 0.99),
            OcrTextBox([285, 45, 315, 60], "117,170", 0.99),
            OcrTextBox([325, 45, 355, 60], "23,434", 0.99),
            OcrTextBox([365, 45, 395, 60], "93,736", 0.99),
            OcrTextBox([405, 45, 435, 60], "0", 0.99),
            OcrTextBox([445, 45, 475, 60], "0", 0.99),
        ]


def test_build_cells_preserves_row_col_order() -> None:
    cells = build_cells(page_id="p001", x_positions=[0, 40, 80], y_positions=[0, 30, 60])

    assert [cell.cell_id for cell in cells] == [
        "p001_r000_c000",
        "p001_r000_c001",
        "p001_r001_c000",
        "p001_r001_c001",
    ]


def test_grid_detection_and_normalize_with_fake_paddle() -> None:
    image = Image.new("RGB", (480, 80), "white")
    draw = ImageDraw.Draw(image)
    for x in range(0, 481, 40):
        draw.line((x, 0, x, 80), fill="black", width=2)
    for y in (0, 30, 80):
        draw.line((0, y, 480, y), fill="black", width=2)

    x_positions, y_positions = detect_grid_lines(image)
    assert len(x_positions) >= 10
    assert len(y_positions) >= 3

    tables = extract_tables_from_image(image, page_id="p001", ocr=FakeOcr(), min_cell_width=10, min_cell_height=10)
    rows, issues = normalize_detail_rows(tables[0], source_file="sample.jpg", page_label="1")

    assert rows
    assert rows[0].validation_status == "verified"
    assert rows[0].total_amount == "117170"
    assert issues == []
