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
    def __init__(self, content: str | None = None, exc: Exception | None = None) -> None:
        self.content = content
        self.exc = exc
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return _Response([_Choice(_Message(self.content or "{}"))])


class _Chat:
    def __init__(self, completions: _Completions) -> None:
        self.completions = completions


class _Client:
    def __init__(self, completions: _Completions) -> None:
        self.chat = _Chat(completions)


def _table_block() -> LayoutBlock:
    table_json = {
        "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
        "rows": [
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
                "신1-5종": "",
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


def test_refine_numeric_cells_applies_valid_corrections_and_marks_raw() -> None:
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
                "1-3종": {"from": "", "to": "1"},
                "1-5종": {"from": "", "to": "1"},
                "신1-5종": {"from": "", "to": "1"}
              }
            },
            {
              "수술명": "골수염 골결핵 수술",
              "수술해설": "뼈에 관한 모든 수술",
              "1-3종": "2",
              "1-5종": "3",
              "신1-5종": ""
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
    assert "_corrections" not in row
    assert result[0].raw["native_table"] is True
    assert result[0].raw["numeric_refined"] is True
    assert result[0].raw["numeric_corrections"] == [
        {"row_index": 0, "col": "1-3종", "from": "", "to": "1"},
        {"row_index": 0, "col": "1-5종", "from": "", "to": "1"},
        {"row_index": 0, "col": "신1-5종", "from": "", "to": "1"},
    ]
    assert "손가락 핀고정술" in result[0].text
    assert completions.calls[0]["model"] == "gpt-4o-mini"


def test_refine_numeric_cells_skips_when_no_candidate_rows() -> None:
    block = _table_block()
    block.table_json["rows"][0]["1-3종"] = "1"
    completions = _Completions("{}")
    client = _Client(completions)

    result = refine_numeric_cells([block], Image.new("RGB", (120, 120), "white"), client)

    assert result == [block]
    assert completions.calls == []


def test_refine_numeric_cells_keeps_original_on_invalid_shape() -> None:
    block = _table_block()
    completions = _Completions('{"headers":["수술명"],"rows":[{"수술명":"변경"}]}')
    client = _Client(completions)

    result = refine_numeric_cells([block], Image.new("RGB", (120, 120), "white"), client)

    assert result[0] is block
    assert "numeric_refined" not in result[0].raw


def test_refine_numeric_cells_ignores_non_numeric_or_non_candidate_corrections() -> None:
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
                "수술명": {"from": "", "to": "2"},
                "1-3종": {"from": "", "to": "4"}
              }
            },
            {
              "수술명": "골수염 골결핵 수술",
              "수술해설": "뼈에 관한 모든 수술",
              "1-3종": "2",
              "1-5종": "3",
              "신1-5종": "",
              "_corrections": {"신1-5종": {"from": "", "to": "1"}}
            }
          ]
        }
        """
    )
    client = _Client(completions)
    original = _table_block()

    result = refine_numeric_cells([original], Image.new("RGB", (120, 120), "white"), client)

    assert result[0] is original
    assert "numeric_refined" not in result[0].raw


def test_refine_numeric_cells_raises_auth_error_for_401() -> None:
    class AuthError(Exception):
        status_code = 401

    client = _Client(_Completions(exc=AuthError("unauthorized")))

    with pytest.raises(NumericCellRefinerAuthError):
        refine_numeric_cells([_table_block()], Image.new("RGB", (120, 120), "white"), client)
