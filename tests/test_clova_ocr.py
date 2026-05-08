from __future__ import annotations

import json

import pytest
from PIL import Image

from src.parser import clova_ocr
from src.parser.clova_ocr import ClovaOcrError, _table_to_json, _table_to_text, _vertices_to_bbox, clova_ocr_page


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
                "cellTextLines": [{"words": [{"text": "수술종수"}]}],
            },
            {
                "rowIndex": 0,
                "columnIndex": 1,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"words": [{"text": "수술명"}]}],
            },
            {
                "rowIndex": 1,
                "columnIndex": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"words": [{"text": "1종"}]}],
            },
            {
                "rowIndex": 1,
                "columnIndex": 1,
                "rowSpan": 1,
                "columnSpan": 1,
                "cellTextLines": [{"words": [{"text": "봉합술"}]}],
            },
        ]
    }

    result = _table_to_json(table)

    assert result["headers"] == ["수술종수", "수술명"]
    assert result["rows"][0] == {"수술종수": "1종", "수술명": "봉합술"}


def test_table_to_text_serializes_header_and_rows() -> None:
    table_json = {"headers": ["수술종수", "수술명"], "rows": [{"수술종수": "1종", "수술명": "봉합술"}]}
    text = _table_to_text(table_json)

    assert "수술종수 | 수술명" in text
    assert "1종 | 봉합술" in text


def test_clova_ocr_page_raises_without_env(monkeypatch) -> None:
    monkeypatch.delenv("CLOVA_OCR_URL", raising=False)
    monkeypatch.delenv("CLOVA_OCR_SECRET", raising=False)

    with pytest.raises(ClovaOcrError, match="환경변수"):
        clova_ocr_page(Image.new("RGB", (10, 10), "white"))


def test_clova_ocr_page_success_response(monkeypatch) -> None:
    monkeypatch.setenv("CLOVA_OCR_URL", "https://example.test/ocr")
    monkeypatch.setenv("CLOVA_OCR_SECRET", "secret-key")

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "images": [
                    {
                        "inferResult": "SUCCESS",
                        "tables": [
                            {
                                "cells": [
                                    {
                                        "rowIndex": 0,
                                        "columnIndex": 0,
                                        "rowSpan": 1,
                                        "columnSpan": 1,
                                        "cellTextLines": [{"words": [{"text": "수술종수"}]}],
                                        "boundingPoly": {
                                            "vertices": [
                                                {"x": 0, "y": 0},
                                                {"x": 30, "y": 0},
                                                {"x": 30, "y": 20},
                                                {"x": 0, "y": 20},
                                            ]
                                        },
                                    },
                                    {
                                        "rowIndex": 0,
                                        "columnIndex": 1,
                                        "rowSpan": 1,
                                        "columnSpan": 1,
                                        "cellTextLines": [{"words": [{"text": "수술명"}]}],
                                        "boundingPoly": {
                                            "vertices": [
                                                {"x": 31, "y": 0},
                                                {"x": 80, "y": 0},
                                                {"x": 80, "y": 20},
                                                {"x": 31, "y": 20},
                                            ]
                                        },
                                    },
                                    {
                                        "rowIndex": 1,
                                        "columnIndex": 0,
                                        "rowSpan": 1,
                                        "columnSpan": 1,
                                        "cellTextLines": [{"words": [{"text": "1종"}]}],
                                        "boundingPoly": {
                                            "vertices": [
                                                {"x": 0, "y": 21},
                                                {"x": 30, "y": 21},
                                                {"x": 30, "y": 40},
                                                {"x": 0, "y": 40},
                                            ]
                                        },
                                    },
                                    {
                                        "rowIndex": 1,
                                        "columnIndex": 1,
                                        "rowSpan": 1,
                                        "columnSpan": 1,
                                        "cellTextLines": [{"words": [{"text": "봉합술"}]}],
                                        "boundingPoly": {
                                            "vertices": [
                                                {"x": 31, "y": 21},
                                                {"x": 80, "y": 21},
                                                {"x": 80, "y": 40},
                                                {"x": 31, "y": 40},
                                            ]
                                        },
                                    },
                                ]
                            }
                        ],
                        "fields": [
                            {
                                "inferText": "수술분류표",
                                "inferConfidence": 0.99,
                                "lineBreak": True,
                                "boundingPoly": {
                                    "vertices": [
                                        {"x": 2, "y": 45},
                                        {"x": 60, "y": 45},
                                        {"x": 60, "y": 60},
                                        {"x": 2, "y": 60},
                                    ]
                                },
                            }
                        ],
                    }
                ]
            }

    def fake_post(url: str, headers: dict, files: dict, timeout: int):  # noqa: ANN001
        assert url == "https://example.test/ocr"
        assert headers["X-OCR-SECRET"] == "secret-key"
        message = files["message"][1]
        parsed = json.loads(message)
        assert parsed["version"] == "V2"
        return DummyResponse()

    monkeypatch.setattr(clova_ocr.requests, "post", fake_post)

    blocks = clova_ocr_page(Image.new("RGB", (100, 100), "white"), page_name="sample")

    assert len(blocks) == 2
    table = next(block for block in blocks if block.block_type == "table")
    assert table.source_method == "ocr_clova"
    assert table.table_json is not None
    assert table.table_json["headers"] == ["수술종수", "수술명"]
    assert table.table_json["rows"][0]["수술명"] == "봉합술"


def test_clova_ocr_page_raises_on_http_error(monkeypatch) -> None:
    monkeypatch.setenv("CLOVA_OCR_URL", "https://example.test/ocr")
    monkeypatch.setenv("CLOVA_OCR_SECRET", "secret-key")

    class DummyResponse:
        def raise_for_status(self) -> None:
            raise clova_ocr.requests.HTTPError("502 Server Error")

    def fake_post(url: str, headers: dict, files: dict, timeout: int):  # noqa: ANN001
        return DummyResponse()

    monkeypatch.setattr(clova_ocr.requests, "post", fake_post)

    with pytest.raises(ClovaOcrError, match="요청 실패"):
        clova_ocr_page(Image.new("RGB", (10, 10), "white"))

