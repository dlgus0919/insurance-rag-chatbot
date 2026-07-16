from src.parser.chunker import Chunk
from src.rag.source_grounded_answers import (
    build_absent_code_guard_answer,
    build_generation_deductible_comparison_answer,
    build_hira_fee_answer,
    build_policy_clause_decision,
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


def _hair_clause(*, generation: str, own_company: bool | None) -> Chunk:
    return Chunk(
        id=f"hair-{generation}",
        text=(
            "노화현상으로 인한 탈모 등 피부질환으로서 업무 또는 일상생활에 지장이 없는 경우에 "
            "실시 또는 사용되는 치료로 인하여 발생한 비급여 의료비에 대해서는 보상하지 않습니다."
        ),
        metadata={
            "policy_generation": generation,
            "is_own_company": own_company,
            "doc_short": "약관" if own_company else "표준약관",
            "page_start": 78 if generation == "4th" else 296,
        },
    )


def test_generic_hair_loss_requires_cause_clarification_without_final_exclusion() -> None:
    decision = build_policy_clause_decision(
        "탈모 보상 가능?",
        [_hair_clause(generation="4th", own_company=True)],
        policy_generation="4th",
    )

    assert decision is not None
    assert decision.payload["status"] == "clarification_required"
    assert "보상 여부를 확정할 수 없습니다" in decision.answer
    assert any("노화현상" in question and "질병성 탈모" in question for question in decision.payload["clarification_questions"])
    assert "진단명 또는 진단코드" in decision.payload["required_evidence"]


def test_age_related_hair_loss_reports_conditional_nonpay_exclusion_from_selected_policy() -> None:
    decision = build_policy_clause_decision(
        "노화현상으로 인한 탈모는 보상 가능한가요?",
        [_hair_clause(generation="5th", own_company=None)],
        policy_generation="5th",
    )

    assert decision is not None
    assert decision.payload["status"] == "conditional_exclusion"
    assert "비급여 의료비" in decision.answer
    assert "업무 또는 일상생활에 지장" in decision.answer
    assert "표준약관" in decision.payload["authority_note"]


def test_hair_loss_decision_prefers_manifested_direct_clause_source() -> None:
    direct = _hair_clause(generation="4th", own_company=True)
    direct.id = "약관_ch_002457"
    duplicate = _hair_clause(generation="4th", own_company=True)
    duplicate.id = "약관_ch_duplicate"

    decision = build_policy_clause_decision(
        "노화현상으로 인한 탈모는 보상 가능한가요?",
        [duplicate, direct],
        policy_generation="4th",
    )

    assert decision is not None
    assert [chunk.id for chunk in decision.chunks] == ["약관_ch_002457"]
    assert [source["chunk_id"] for source in decision.payload["source_evidence"]] == ["약관_ch_002457"]


def test_disease_related_hair_loss_does_not_auto_apply_age_related_exclusion() -> None:
    decision = build_policy_clause_decision(
        "질병 진단으로 인한 탈모 치료는?",
        [_hair_clause(generation="4th", own_company=True)],
        policy_generation="4th",
    )

    assert decision is not None
    assert decision.payload["status"] == "clarification_required"
    assert "자동 적용할 수 없습니다" in decision.answer
    assert "보상 가능으로 확정" not in decision.answer
