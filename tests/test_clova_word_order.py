from __future__ import annotations

from src.parser.clova_ocr import _fields_to_lines, _group_fields_into_rows


def make_field(x1: int, y1: int, x2: int, y2: int, text: str, line_break: bool = False) -> dict:
    return {
        "inferText": text,
        "lineBreak": line_break,
        "inferConfidence": 0.99,
        "boundingPoly": {
            "vertices": [
                {"x": x1, "y": y1},
                {"x": x2, "y": y1},
                {"x": x2, "y": y2},
                {"x": x1, "y": y2},
            ]
        },
    }


def test_linebreak_in_middle_does_not_split() -> None:
    fields = [
        make_field(0, 10, 20, 30, "손가락", line_break=True),
        make_field(24, 11, 44, 31, "골절"),
        make_field(48, 12, 68, 32, "고정술"),
    ]

    assert _fields_to_lines(fields, row_gap=8.0) == "손가락 골절 고정술"


def test_same_line_words_different_y() -> None:
    fields = [
        make_field(0, 10, 20, 30, "보험금"),
        make_field(24, 16, 44, 36, "지급"),
        make_field(48, 18, 68, 38, "심사"),
    ]

    assert _fields_to_lines(fields, row_gap=10.0) == "보험금 지급 심사"


def test_two_lines_separated_by_y_gap() -> None:
    fields = [
        make_field(0, 10, 20, 30, "첫째"),
        make_field(24, 11, 44, 31, "줄"),
        make_field(0, 42, 20, 62, "둘째"),
        make_field(24, 43, 44, 63, "줄"),
    ]

    assert _fields_to_lines(fields, row_gap=10.0) == "첫째 줄\n둘째 줄"


def test_adaptive_row_gap_uses_field_height() -> None:
    fields = [
        make_field(0, 10, 20, 40, "높은"),
        make_field(24, 24, 44, 54, "글자"),
    ]

    assert _fields_to_lines(fields) == "높은 글자"


def test_group_fields_into_rows_adaptive() -> None:
    fields = [
        make_field(0, 10, 20, 50, "A"),
        make_field(24, 29, 44, 69, "B"),
        make_field(0, 90, 20, 130, "C"),
    ]

    rows = _group_fields_into_rows(fields)

    assert [[field["inferText"] for field in row] for row in rows] == [["A", "B"], ["C"]]
