from __future__ import annotations

from dataclasses import dataclass

from PIL import Image
import pytest

from src.parser.numeric_cell_refiner import NumericCellRefinerAuthError, refine_numeric_cells
from src.parser.ocr_engine import LayoutBlock


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]


class _Completions:
    def __init__(self, content: str | list[str] | None = None, exc: Exception | None = None) -> None:
        self.contents = content if isinstance(content, list) else [content or "{}"]
        self.exc = exc
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        index = min(len(self.calls) - 1, len(self.contents) - 1)
        return _Response([_Choice(_Message(self.contents[index] or "{}"))])


class _Chat:
    def __init__(self, completions: _Completions) -> None:
        self.completions = completions


class _Client:
    def __init__(self, completions: _Completions) -> None:
        self.chat = _Chat(completions)


def _table_block(rows: list[dict] | None = None, headers: list[str] | None = None) -> LayoutBlock:
    table_json = {
        "headers": headers or ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
        "rows": rows
        or [
            {
                "수술명": "손가락 핀고정술",
                "수술해설": "손가락 골절시 관혈 또는 경피적으로 핀을 삽입",
                "1-3종": "",
                "1-5종": "",
                "신1-5종": "",
            },
            {
                "수술명": "골수염 골결핵 수술",
                "수술해설": "뼈에 관한 모든 수술",
                "1-3종": "2",
                "1-5종": "3",
                "신1-5종": "2",
            },
        ],
    }
    return LayoutBlock(
        block_type="table",
        bbox=[0, 0, 100, 100],
        text="",
        table_json=table_json,
        raw={"native_table": True},
    )


def test_refine_numeric_cells_applies_all_blank_text_row_corrections() -> None:
    completions = _Completions(
        """
        {
          "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
          "rows": [
            {
              "수술명": "손가락 핀고정술",
              "수술해설": "손가락 골절시 관혈 또는 경피적으로 핀을 삽입",
              "1-3종": "",
              "1-5종": "",
              "신1-5종": "",
              "_corrections": {
                "1-3종": {"from": "", "to": "1", "confidence": "high"},
                "1-5종": {"from": "", "to": "1", "confidence": "medium"},
                "신1-5종": {"from": "", "to": "1", "confidence": "low"}
              }
            },
            {
              "수술명": "골수염 골결핵 수술",
              "수술해설": "뼈에 관한 모든 수술",
              "1-3종": "2",
              "1-5종": "3",
              "신1-5종": "2"
            }
          ]
        }
        """
    )
    client = _Client(completions)

    result = refine_numeric_cells([_table_block()], Image.new("RGB", (120, 120), "white"), client)

    row = result[0].table_json["rows"][0]
    assert row["1-3종"] == "1"
    assert row["1-5종"] == "1"
    assert row["신1-5종"] == "1"
    assert result[0].raw["numeric_candidate_rows"] == [0]
    assert result[0].raw["numeric_refined"] is True
    assert result[0].raw["numeric_corrections"] == [
        {
            "row_index": 0,
            "col": "1-3종",
            "from": "",
            "to": "1",
            "method": "vision_llm",
            "reason": "complete_surgery_grade_group",
            "confidence": "high",
        },
        {
            "row_index": 0,
            "col": "1-5종",
            "from": "",
            "to": "1",
            "method": "vision_llm",
            "reason": "complete_surgery_grade_group",
            "confidence": "medium",
        },
        {
            "row_index": 0,
            "col": "신1-5종",
            "from": "",
            "to": "1",
            "method": "vision_llm",
            "reason": "complete_surgery_grade_group",
            "confidence": "low",
        },
    ]
    assert completions.calls[0]["model"] == "gpt-4.1"
    assert len(completions.calls[0]["messages"][0]["content"]) == 3


def test_refine_numeric_cells_includes_partial_missing_rows() -> None:
    rows = [
        {
            "수술명": "근육내 양성종양 적출술",
            "수술해설": "근육내 양성종양을 제거",
            "1-3종": "1",
            "1-5종": "",
            "신1-5종": "",
        }
    ]
    completions = _Completions(
        """
        {
          "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
          "rows": [
            {
              "수술명": "근육내 양성종양 적출술",
              "수술해설": "근육내 양성종양을 제거",
              "1-3종": "1",
              "1-5종": "",
              "신1-5종": "",
              "_corrections": {
                "1-5종": {"from": "", "to": "1", "confidence": "high"},
                "신1-5종": {"from": "", "to": "1", "confidence": "high"}
              }
            }
          ]
        }
        """
    )
    client = _Client(completions)

    result = refine_numeric_cells([_table_block(rows)], Image.new("RGB", (120, 120), "white"), client)

    assert result[0].table_json["rows"][0]["1-3종"] == "1"
    assert result[0].table_json["rows"][0]["1-5종"] == "1"
    assert result[0].table_json["rows"][0]["신1-5종"] == "1"
    assert [item["col"] for item in result[0].raw["numeric_corrections"]] == ["1-5종", "신1-5종"]
    prompt = completions.calls[0]["messages"][0]["content"][2]["text"]
    assert '"1-5종"' in prompt
    assert '"신1-5종"' in prompt


def test_refine_numeric_cells_skips_figure_and_empty_all_blank_rows() -> None:
    rows = [
        {"수술명": "[그림]", "수술해설": "", "1-3종": "", "1-5종": "", "신1-5종": ""},
        {"수술명": "", "수술해설": "", "1-3종": "", "1-5종": "", "신1-5종": ""},
        {"수술명": "완성 행", "수술해설": "설명", "1-3종": "N", "1-5종": "N", "신1-5종": "N"},
    ]
    completions = _Completions("{}")
    client = _Client(completions)

    result = refine_numeric_cells([_table_block(rows)], Image.new("RGB", (120, 120), "white"), client)

    assert result[0].raw == {"native_table": True}
    assert completions.calls == []


def test_refine_numeric_cells_validates_allowed_values_and_marks_unresolved() -> None:
    rows = [
        {"수술명": "부분 누락", "수술해설": "설명", "1-3종": "N", "1-5종": "", "신1-5종": "N"},
        {"수술명": "잘못된 값", "수술해설": "설명", "1-3종": "4", "1-5종": "3", "신1-5종": "2"},
    ]
    completions = _Completions(
        """
        {
          "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
          "rows": [
            {
              "수술명": "부분 누락",
              "수술해설": "설명",
              "1-3종": "N",
              "1-5종": "",
              "신1-5종": "N",
              "_unresolved": {"1-5종": {"from": "", "reason": "not_readable"}}
            },
            {
              "수술명": "잘못된 값",
              "수술해설": "설명",
              "1-3종": "4",
              "1-5종": "3",
              "신1-5종": "2",
              "_corrections": {"1-3종": {"from": "4", "to": "9", "confidence": "high"}}
            }
          ]
        }
        """
    )
    client = _Client(completions)

    result = refine_numeric_cells([_table_block(rows)], Image.new("RGB", (120, 120), "white"), client)

    assert "numeric_refined" not in result[0].raw
    assert result[0].raw["numeric_candidate_rows"] == [0, 1]
    assert result[0].raw["numeric_unresolved_cells"] == [
        {"row_index": 0, "col": "1-5종", "from": "", "reason": "not_readable"},
        {"row_index": 1, "col": "1-3종", "from": "4", "reason": "invalid_vision_value"},
    ]


def test_refine_numeric_cells_supports_surgery_grade_headers() -> None:
    headers = ["수술명", "수술해설", "수술종수", "수술종수_2", "수술종수_3"]
    rows = [{"수술명": "핀고정술", "수술해설": "설명", "수술종수": "", "수술종수_2": "2", "수술종수_3": "2"}]
    completions = _Completions(
        """
        {
          "headers": ["수술명", "수술해설", "수술종수", "수술종수_2", "수술종수_3"],
          "rows": [
            {
              "수술명": "핀고정술",
              "수술해설": "설명",
              "수술종수": "",
              "수술종수_2": "2",
              "수술종수_3": "2",
              "_corrections": {"수술종수": {"from": "", "to": "1", "confidence": "medium"}}
            }
          ]
        }
        """
    )
    client = _Client(completions)

    result = refine_numeric_cells([_table_block(rows, headers)], Image.new("RGB", (120, 120), "white"), client)

    assert result[0].table_json["rows"][0]["수술종수"] == "1"
    assert result[0].raw["numeric_corrections"][0]["col"] == "수술종수"


def test_refine_numeric_cells_keeps_original_on_invalid_shape_after_retry() -> None:
    block = _table_block()
    completions = _Completions(['{"headers":["수술명"],"rows":[{"수술명":"변경"}]}'])
    client = _Client(completions)

    result = refine_numeric_cells([block], Image.new("RGB", (120, 120), "white"), client)

    assert result[0] is block
    assert "numeric_refined" not in result[0].raw
    assert len(completions.calls) == 2


def test_refine_numeric_cells_raises_auth_error_for_401() -> None:
    class AuthError(Exception):
        status_code = 401

    client = _Client(_Completions(exc=AuthError("unauthorized")))

    with pytest.raises(NumericCellRefinerAuthError):
        refine_numeric_cells([_table_block()], Image.new("RGB", (120, 120), "white"), client)
