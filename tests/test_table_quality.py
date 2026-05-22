from __future__ import annotations

from src.parser.table_quality import evaluate_table_quality


def test_table_quality_downcasts_when_rows_empty() -> None:
    should_downcast, reason = evaluate_table_quality({"headers": ["제목"], "rows": []})
    assert should_downcast is True
    assert reason == "rows_empty"


def test_table_quality_downcasts_single_column_prose() -> None:
    should_downcast, reason = evaluate_table_quality(
        {
            "headers": ["판례 내용"],
            "rows": [
                {"판례 내용": "보험금 지급 판단 시 계약의 중요사항을 종합적으로 고려하여야 한다."},
                {"판례 내용": "해당 문단은 표 구조가 아니라 인용 박스 본문에 해당한다."},
            ],
        }
    )
    assert should_downcast is True
    assert reason == "single_column_prose_like"


def test_table_quality_keeps_structured_surgery_table() -> None:
    should_downcast, reason = evaluate_table_quality(
        {
            "headers": ["수술명", "1-3종", "1-5종", "신1-5종"],
            "rows": [{"수술명": "충수절제술", "1-3종": "2", "1-5종": "3", "신1-5종": "2"}],
        }
    )
    assert should_downcast is False
    assert reason is None
