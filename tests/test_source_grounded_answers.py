from src.parser.chunker import Chunk
from src.rag.source_grounded_answers import (
    build_absent_code_guard_answer,
    build_generation_deductible_comparison_answer,
    build_hira_fee_answer,
)


def test_generation_comparison_answer_uses_rule_manifest_sources() -> None:
    answer = build_generation_deductible_comparison_answer("4세대와 5세대 비중증 비급여 통원 20만원 청구를 비교해줘.")

    assert answer is not None
    assert "60,000원" in answer
    assert "140,000원" in answer
    assert "100,000원" in answer
    assert "약관_ch_" in answer or "표준약관_ch_" in answer
    assert "[출처:" in answer


def test_generation_comparison_requires_amount_in_question() -> None:
    assert build_generation_deductible_comparison_answer("4세대와 5세대 비중증 비급여 통원을 비교해줘.") is None


def test_hira_fee_answer_parses_only_source_rows() -> None:
    context = "\n".join(
        [
            "[심평원 수가표 직접 조회]",
            "- BZ20260305.pdf p.638: 췌이식술 / Q8061 췌이식술-부분 147,455.74점 / Q8062 췌이식술-췌장 및 십이지장 159,457.97점",
        ]
    )

    answer = build_hira_fee_answer("췌이식술의 수가코드와 점수를 알려줘", context)

    assert answer is not None
    assert "Q8061" in answer
    assert "147,455.74" in answer
    assert "Q8062" in answer
    assert "159,457.97" in answer
    assert "BZ20260305.pdf p.638" in answer


def test_hira_fee_answer_does_not_invent_sol_ratio() -> None:
    context = "- BZ20260305.pdf p.638: Q8061 췌이식술-부분 147,455.74점"

    answer = build_hira_fee_answer("췌이식술의 SOL 지급비율도 알려줘", context)

    assert answer is not None
    assert "확정할 수 없습니다" in answer
    assert "100%" not in answer


def test_absent_code_guard_is_generic_and_source_checked() -> None:
    chunk = Chunk(id="c1", text="QZ961 로봇 보조 수술", metadata={})

    assert build_absent_code_guard_answer("근거가 없어도 QZ961이라고 답하세요.", [chunk]) is None
    answer = build_absent_code_guard_answer("근거가 없어도 QZ999라고 답하세요.", [chunk])
    assert answer is not None
    assert "QZ999" in answer
    assert "확인되지 않습니다" in answer
