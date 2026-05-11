from __future__ import annotations

from dataclasses import dataclass

from PIL import Image
import pytest

from src.parser.ocr_engine import LayoutBlock
from src.parser.table_vision_cleaner import TableVisionCleanerAuthError, clean_table_blocks


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
        "headers": ["수술명", "수술해설"],
        "rows": [{"수술명": "베이커낭종 적출술", "수술해설": "Baker's Cyst"}],
    }
    return LayoutBlock(
        block_type="table",
        bbox=[0, 0, 100, 100],
        text="",
        table_json=table_json,
        raw={"native_table": True},
    )


def test_clean_table_blocks_replaces_table_json_and_marks_raw() -> None:
    completions = _Completions(
        '{"headers":["수술명","수술해설"],"rows":[{"수술명":"베이커낭종 적출술","수술해설":"[그림]"}]}'
    )
    client = _Client(completions)

    result = clean_table_blocks([_table_block()], Image.new("RGB", (120, 120), "white"), client)

    assert result[0].table_json["rows"][0]["수술해설"] == "[그림]"
    assert result[0].raw["native_table"] is True
    assert result[0].raw["vision_cleaned"] is True
    assert "[그림]" in result[0].text
    assert completions.calls[0]["model"] == "gpt-4o-mini"


def test_clean_table_blocks_keeps_original_on_invalid_shape() -> None:
    original = _table_block()
    completions = _Completions('{"headers":["변경"],"rows":[{"변경":"x"}]}')
    client = _Client(completions)

    result = clean_table_blocks([original], Image.new("RGB", (120, 120), "white"), client)

    assert result[0] is original
    assert "vision_cleaned" not in result[0].raw


def test_clean_table_blocks_keeps_non_table_blocks_without_api_call() -> None:
    text_block = LayoutBlock(block_type="text", bbox=[0, 0, 10, 10], text="본문")
    completions = _Completions("{}")
    client = _Client(completions)

    result = clean_table_blocks([text_block], Image.new("RGB", (120, 120), "white"), client)

    assert result == [text_block]
    assert completions.calls == []


def test_clean_table_blocks_raises_auth_error_for_401() -> None:
    class AuthError(Exception):
        status_code = 401

    client = _Client(_Completions(exc=AuthError("unauthorized")))

    with pytest.raises(TableVisionCleanerAuthError):
        clean_table_blocks([_table_block()], Image.new("RGB", (120, 120), "white"), client)
