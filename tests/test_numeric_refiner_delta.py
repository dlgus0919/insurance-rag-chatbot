from __future__ import annotations

from src.parser.numeric_cell_refiner import _extract_valid_corrections_and_unresolved


GRADE_ROLES = [
    {"col": "1-3종", "role": "1-3종", "allowed": {"N", "1", "2", "3"}},
    {"col": "1-5종", "role": "1-5종", "allowed": {"N", "1", "2", "3", "4", "5"}},
    {"col": "신1-5종", "role": "신1-5종", "allowed": {"N", "1", "2", "3", "4", "5"}},
]


def _table(rows: list[dict]) -> dict:
    return {"headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"], "rows": rows}


def test_delta_format_corrections_applied() -> None:
    original = _table(
        [{"수술명": "핀고정술", "수술해설": "설명", "1-3종": "", "1-5종": "", "신1-5종": ""}]
    )
    delta = {
        "corrections": [
            {"row_index": 0, "col": "1-3종", "to": "1", "confidence": "high"},
            {"row_index": 0, "col": "1-5종", "to": "1", "confidence": "medium"},
            {"row_index": 0, "col": "신1-5종", "to": "1", "confidence": "low"},
        ]
    }

    corrections, unresolved = _extract_valid_corrections_and_unresolved(original, delta, GRADE_ROLES, [0])

    assert [item["to"] for item in corrections] == ["1", "1", "1"]
    assert [item["confidence"] for item in corrections] == ["high", "medium", "low"]
    assert unresolved == []


def test_delta_format_compact_rows_applied() -> None:
    original = _table(
        [{"수술명": "핀고정술", "수술해설": "설명", "1-3종": "", "1-5종": "", "신1-5종": ""}]
    )
    delta = {
        "rows": [
            {
                "row_index": 0,
                "values": {"1-3종": "1", "1-5종": "1", "신1-5종": "1"},
                "confidence": "high",
            }
        ]
    }

    corrections, unresolved = _extract_valid_corrections_and_unresolved(original, delta, GRADE_ROLES, [0])

    assert [item["to"] for item in corrections] == ["1", "1", "1"]
    assert [item["confidence"] for item in corrections] == ["high", "high", "high"]
    assert unresolved == []


def test_delta_format_invalid_value_rejected() -> None:
    original = _table(
        [{"수술명": "잘못된 값", "수술해설": "설명", "1-3종": "4", "1-5종": "3", "신1-5종": "2"}]
    )
    delta = {"corrections": [{"row_index": 0, "col": "1-3종", "to": "9", "confidence": "high"}]}

    corrections, unresolved = _extract_valid_corrections_and_unresolved(original, delta, GRADE_ROLES, [0])

    assert corrections == []
    assert unresolved == [{"row_index": 0, "col": "1-3종", "from": "4", "reason": "invalid_vision_value"}]


def test_delta_format_missing_row_logged() -> None:
    original = _table(
        [{"수술명": "부분 누락", "수술해설": "설명", "1-3종": "N", "1-5종": "", "신1-5종": "N"}]
    )
    delta = {"corrections": []}

    corrections, unresolved = _extract_valid_corrections_and_unresolved(original, delta, GRADE_ROLES, [0])

    assert corrections == []
    assert unresolved == [{"row_index": 0, "col": "1-5종", "from": "", "reason": "missing_vision_correction"}]
