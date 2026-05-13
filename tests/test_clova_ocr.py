from __future__ import annotations

import json

import pytest
from PIL import Image

from src.parser import clova_ocr
from src.parser.clova_ocr import (
    ClovaOcrError,
    _assign_fields_to_columns,
    _detect_column_x_ranges,
    _group_fields_into_rows,
    _table_to_json,
    _table_to_text,
    _vertices_to_bbox,
    clova_ocr_page,
    reconstruct_table_from_fields,
)


def _field(text: str, x1: int, y1: int, x2: int, y2: int, *, line_break: bool = False, conf: float = 0.99) -> dict:
    return {
        "inferText": text,
        "inferConfidence": conf,
        "lineBreak": line_break,
        "boundingPoly": {
            "vertices": [
                {"x": x1, "y": y1},
                {"x": x2, "y": y1},
                {"x": x2, "y": y2},
                {"x": x1, "y": y2},
            ]
        },
    }


MOCK_TABLE_FIELDS = [
    _field("수술종수", 100, 90, 200, 110),
    _field("수술명", 300, 90, 500, 110),
    _field("수술해설", 600, 90, 1000, 110, line_break=True),
    _field("1-3종", 100, 140, 200, 160),
    _field("반월판연골봉합술", 300, 140, 500, 160),
    _field("파열된 반월판을 꿰매는 수술", 600, 140, 1000, 160, line_break=True),
]


def test_vertices_to_bbox_handles_empty_vertices() -> None:
    assert _vertices_to_bbox([]) == (0, 0, 0, 0)
    assert _vertices_to_bbox([{"x": 10, "y": 20}, {"x": 40, "y": 60}]) == (10, 20, 40, 60)


def test_table_to_json_merges_cells_and_serializes_rows() -> None:
    table = {
        "cells": [
            {
                "rowIndex": 0,
                "columnIndex": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "수술종수"}]}],
            },
            {
                "rowIndex": 0,
                "columnIndex": 1,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "수술명"}]}],
            },
            {
                "rowIndex": 1,
                "columnIndex": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "1종"}]}],
            },
            {
                "rowIndex": 1,
                "columnIndex": 1,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "봉합술"}]}],
            },
        ]
    }

    result = _table_to_json(table)

    assert result["headers"] == ["수술종수", "수술명"]
    assert result["rows"][0] == {"수술종수": "1종", "수술명": "봉합술"}


def test_table_to_json_uses_second_header_row_for_colspan_group() -> None:
    table = {
        "cells": [
            {
                "rowIndex": 0,
                "columnIndex": 0,
                "rowSpan": 2,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "수술명"}]}],
            },
            {
                "rowIndex": 0,
                "columnIndex": 1,
                "rowSpan": 2,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "수술해설"}]}],
            },
            {
                "rowIndex": 0,
                "columnIndex": 2,
                "rowSpan": 1,
                "columnSpan": 3,
                "cellTextLines": [{"cellWords": [{"inferText": "수술종수"}]}],
            },
            {
                "rowIndex": 1,
                "columnIndex": 2,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "1-3종"}]}],
            },
            {
                "rowIndex": 1,
                "columnIndex": 3,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "1-5종"}]}],
            },
            {
                "rowIndex": 1,
                "columnIndex": 4,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "신1-5종"}]}],
            },
            {
                "rowIndex": 2,
                "columnIndex": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "봉합술"}]}],
            },
            {
                "rowIndex": 2,
                "columnIndex": 1,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "설명"}]}],
            },
            {
                "rowIndex": 2,
                "columnIndex": 3,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "2"}]}],
            },
            {
                "rowIndex": 2,
                "columnIndex": 4,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "2"}]}],
            },
        ]
    }

    result = _table_to_json(table)

    assert result["headers"] == ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"]
    assert result["rows"][0] == {"수술명": "봉합술", "수술해설": "설명", "1-3종": "", "1-5종": "2", "신1-5종": "2"}


def test_request_clova_includes_enable_table_detection(monkeypatch) -> None:
    monkeypatch.setenv("CLOVA_OCR_URL", "https://example.test/ocr")
    monkeypatch.setenv("CLOVA_OCR_SECRET", "secret-key")
    captured: dict = {}

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"images": [{"inferResult": "SUCCESS", "fields": [], "tables": []}]}

    def fake_post(url: str, headers: dict, files: dict, timeout: int):  # noqa: ANN001
        captured["message"] = json.loads(files["message"][1])
        return DummyResponse()

    monkeypatch.setattr(clova_ocr.requests, "post", fake_post)

    result = clova_ocr._request_clova(Image.new("RGB", (10, 10), "white"), page_name="sample")

    assert result["tables"] == []
    assert captured["message"]["enableTableDetection"] is True


def test_table_to_text_serializes_header_and_rows() -> None:
    table_json = {"headers": ["수술종수", "수술명"], "rows": [{"수술종수": "1종", "수술명": "봉합술"}]}
    text = _table_to_text(table_json)
    assert "수술종수 | 수술명" in text
    assert "1종 | 봉합술" in text


def test_group_fields_into_rows() -> None:
    rows = _group_fields_into_rows(MOCK_TABLE_FIELDS, row_gap=20.0)
    assert len(rows) == 2
    assert rows[0][0]["inferText"] == "수술종수"
    assert rows[1][0]["inferText"] == "1-3종"


def test_detect_column_x_ranges() -> None:
    rows = _group_fields_into_rows(MOCK_TABLE_FIELDS, row_gap=20.0)
    ranges = _detect_column_x_ranges(rows, col_gap=40.0)
    assert len(ranges) == 3
    assert ranges[0][0] <= 100 <= ranges[0][1]
    assert ranges[1][0] <= 300 <= ranges[1][1]
    assert ranges[2][0] <= 600 <= ranges[2][1]


def test_assign_fields_to_columns() -> None:
    rows = _group_fields_into_rows(MOCK_TABLE_FIELDS, row_gap=20.0)
    ranges = _detect_column_x_ranges(rows, col_gap=40.0)
    cells = _assign_fields_to_columns(rows[1], ranges)
    assert cells[0] == "1-3종"
    assert cells[1] == "반월판연골봉합술"
    assert "파열된 반월판" in cells[2]


def test_reconstruct_table_from_fields() -> None:
    table_json = reconstruct_table_from_fields(MOCK_TABLE_FIELDS, (80, 80, 1050, 180))
    assert table_json["headers"] == ["수술종수", "수술명", "수술해설"]
    assert table_json["rows"][0]["수술명"] == "반월판연골봉합술"
    assert "파열된 반월판" in table_json["rows"][0]["수술해설"]


def test_clova_ocr_page_raises_without_env(monkeypatch) -> None:
    monkeypatch.delenv("CLOVA_OCR_URL", raising=False)
    monkeypatch.delenv("CLOVA_OCR_SECRET", raising=False)
    with pytest.raises(ClovaOcrError, match="환경변수"):
        clova_ocr_page(Image.new("RGB", (10, 10), "white"))


def test_clova_ocr_page_returns_single_text_when_layout_none(monkeypatch) -> None:
    monkeypatch.setenv("CLOVA_OCR_URL", "https://example.test/ocr")
    monkeypatch.setenv("CLOVA_OCR_SECRET", "secret-key")

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"images": [{"inferResult": "SUCCESS", "fields": [_field("수술분류표", 10, 10, 80, 30, line_break=True)]}]}

    def fake_post(url: str, headers: dict, files: dict, timeout: int):  # noqa: ANN001
        assert timeout == 60
        message = json.loads(files["message"][1])
        assert message["version"] == "V2"
        return DummyResponse()

    monkeypatch.setattr(clova_ocr.requests, "post", fake_post)

    blocks = clova_ocr_page(Image.new("RGB", (100, 100), "white"))
    assert len(blocks) == 1
    assert blocks[0].block_type == "text"
    assert "수술분류표" in blocks[0].text


def test_clova_ocr_page_with_layout_regions(monkeypatch) -> None:
    monkeypatch.setenv("CLOVA_OCR_URL", "https://example.test/ocr")
    monkeypatch.setenv("CLOVA_OCR_SECRET", "secret-key")

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            fields = [_field("제1장 수술분류표 해설", 90, 40, 350, 70, line_break=True)] + MOCK_TABLE_FIELDS
            return {"images": [{"inferResult": "SUCCESS", "fields": fields}]}

    monkeypatch.setattr(clova_ocr.requests, "post", lambda *args, **kwargs: DummyResponse())

    layout_regions = [
        {"type": "text", "bbox": [70, 30, 420, 80]},
        {"type": "table", "bbox": [80, 80, 1050, 180]},
        {"type": "figure", "bbox": [0, 0, 20, 20]},
    ]
    blocks = clova_ocr_page(Image.new("RGB", (1200, 300), "white"), page_name="sample", layout_regions=layout_regions)

    table = next(block for block in blocks if block.block_type == "table")
    text = next(block for block in blocks if block.block_type == "text")
    assert table.source_method == "ocr_clova"
    assert table.table_json is not None
    assert table.table_json["headers"] == ["수술종수", "수술명", "수술해설"]
    assert table.table_json["rows"][0]["수술종수"] == "1-3종"
    assert "수술분류표" in text.text
    assert all(block.block_type != "figure" for block in blocks)


def test_clova_ocr_page_uses_native_tables_when_present(monkeypatch) -> None:
    native_table = {
        "boundingPoly": {
            "vertices": [
                {"x": 80, "y": 80},
                {"x": 520, "y": 80},
                {"x": 520, "y": 180},
                {"x": 80, "y": 180},
            ]
        },
        "cells": [
            {
                "rowIndex": 0,
                "columnIndex": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "수술종수"}]}],
            },
            {
                "rowIndex": 0,
                "columnIndex": 1,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "수술명"}]}],
            },
            {
                "rowIndex": 1,
                "columnIndex": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "1종"}]}],
            },
            {
                "rowIndex": 1,
                "columnIndex": 1,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"cellWords": [{"inferText": "봉합술"}]}],
            },
        ],
    }

    def fake_request_clova(image, page_name: str, timeout_sec: int | None = None) -> dict:  # noqa: ANN001
        return {
            "fields": [
                _field("수술종수", 100, 90, 180, 110),
                _field("수술명", 300, 90, 380, 110, line_break=True),
                _field("1종", 100, 140, 180, 160),
                _field("봉합술", 300, 140, 380, 160, line_break=True),
                _field("표 밖 텍스트", 90, 210, 240, 230, line_break=True),
            ],
            "tables": [native_table],
        }

    def fail_reconstruct_table_from_fields(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("native tables should bypass geometric reconstruction")

    monkeypatch.setattr(clova_ocr, "_request_clova", fake_request_clova)
    monkeypatch.setattr(clova_ocr, "reconstruct_table_from_fields", fail_reconstruct_table_from_fields)

    blocks = clova_ocr_page(
        Image.new("RGB", (600, 300), "white"),
        page_name="sample",
        layout_regions=[{"type": "table", "bbox": [80, 80, 520, 180]}],
    )

    table = next(block for block in blocks if block.block_type == "table")
    assert table.raw == {"native_table": True}
    assert table.bbox == [80, 80, 520, 180]
    assert table.table_json is not None
    assert table.table_json["headers"] == ["수술종수", "수술명"]
    assert table.table_json["rows"][0] == {"수술종수": "1종", "수술명": "봉합술"}
    assert "표 밖 텍스트" in blocks[-1].text


def test_clova_ocr_page_splits_remainder_into_multiple_paragraph_blocks(monkeypatch) -> None:
    def fake_request_clova(image, page_name: str, timeout_sec: int | None = None) -> dict:  # noqa: ANN001
        return {
            "fields": [
                _field("제목", 20, 10, 80, 30, line_break=True),
                _field("본문", 140, 34, 200, 54),
            ],
            "tables": [],
        }

    monkeypatch.setattr(clova_ocr, "_request_clova", fake_request_clova)

    blocks = clova_ocr_page(
        Image.new("RGB", (400, 200), "white"),
        page_name="sample",
        layout_regions=[],
    )

    text_blocks = [block for block in blocks if block.block_type == "text"]
    assert len(text_blocks) == 2
    assert text_blocks[0].text == "제목"
    assert text_blocks[1].text == "본문"


def test_clova_ocr_page_raises_on_http_error(monkeypatch) -> None:
    monkeypatch.setenv("CLOVA_OCR_URL", "https://example.test/ocr")
    monkeypatch.setenv("CLOVA_OCR_SECRET", "secret-key")

    class DummyResponse:
        def raise_for_status(self) -> None:
            raise clova_ocr.requests.HTTPError("502 Server Error")

    monkeypatch.setattr(clova_ocr.requests, "post", lambda *args, **kwargs: DummyResponse())

    with pytest.raises(ClovaOcrError, match="API 요청 실패"):
        clova_ocr_page(Image.new("RGB", (10, 10), "white"))
