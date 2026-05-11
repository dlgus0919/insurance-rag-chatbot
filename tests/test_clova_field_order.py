from __future__ import annotations

from src.parser.clova_ocr import _fields_to_lines
from tests.test_clova_word_order import make_field


def test_clova_original_order_preserved_over_x_sort() -> None:
    fields = [
        make_field(70, 10, 110, 30, "원칙적으로"),
        make_field(40, 11, 65, 31, "각각"),
    ]

    assert _fields_to_lines(fields, row_gap=5.0) == "원칙적으로 각각"


def test_swapped_bbox_x_uses_original_index() -> None:
    fields = [
        make_field(90, 10, 120, 30, "생기고"),
        make_field(55, 11, 85, 31, "다른"),
        make_field(125, 12, 160, 32, "1관절에"),
    ]

    assert _fields_to_lines(fields, row_gap=5.0) == "생기고 다른 1관절에"


def test_two_rows_x_sort_not_applied() -> None:
    fields = [
        make_field(100, 10, 140, 30, "A"),
        make_field(30, 11, 70, 31, "B"),
    ]

    assert _fields_to_lines(fields, row_gap=5.0) == "A B"


def test_cross_row_order_still_correct() -> None:
    fields = [
        make_field(100, 50, 140, 70, "둘째"),
        make_field(30, 10, 70, 30, "첫째"),
        make_field(80, 51, 120, 71, "줄"),
        make_field(80, 11, 120, 31, "줄"),
    ]

    assert _fields_to_lines(fields, row_gap=5.0) == "첫째 줄\n둘째 줄"
