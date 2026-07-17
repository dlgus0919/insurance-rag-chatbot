"""보험금 계산 파이프라인 통합 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from decimal import Decimal
import pytest

from src.claim_calculation.models import ClaimItemInput, ClaimCaseContext, CalculationResult
from src.claim_calculation.pipeline import run_claim_calculation


def _matches_for(items: list[ClaimItemInput]) -> list[list[dict[str, str]]]:
    return [
        [{
            "std_cd": f"STD{i + 1:03d}",
            "std_cd_nm": item.input_name,
            "mid_category_cd_nm": item.user_category_hint or "급여",
            "pay_opn_cd_nm": "보상",
        }]
        for i, item in enumerate(items)
    ]


def test_pipeline_dousu_unknown_special_status_requires_review():
    """기본 5세대 도수치료는 산정특례 상태가 없으면 자동 산정하지 않고 review 사유를 남긴다.

    한도/횟수/특약 조건을 확인할 증빙이 입력되지 않은 실제 심사 화면에서는 review path가
    별도로 붙을 수 있다. 이 단위 테스트는 산정특례 상태가 케이스 단위로 확인되지 않은
    5세대 3대비급여 항목을 자동 지급액에 합산하지 않는 안전 경로를 검증한다.
    """
    items = [
        ClaimItemInput(
            line_id="item_1",
            input_name="도수치료",
            claimed_amount="150000",
            quantity="1"
        )
    ]
    context = ClaimCaseContext(
        situation_note="도수치료 1회 청구",
        visit_type="outpatient"
    )

    mock_match = {
        "std_cd": "SC0001",
        "std_cd_nm": "도수치료",
        "mid_category_cd_nm": "물리치료",
        "pay_opn_cd_nm": "보상",  # 보상 가능 의견
    }

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result: CalculationResult = run_claim_calculation(
            rag_pipeline=None,
            items=items,
            context=context,
            basis_mode="auto",
            use_fake_planner=True
        )

        assert isinstance(result, CalculationResult)
        assert result.payable_amount == "0"
        assert result.deductible == "0"
        assert result.policy_generation == "5th"
        assert result.line_results[0]["payable_amount"] == "0"
        assert result.line_results[0]["calculation_status"] == "human_task"
        assert result.requires_review
        assert len(result.applied_basis) > 0
        assert any("산정특례 적용 여부" in reason for reason in result.line_results[0]["review_reasons"])


def test_unsupported_policy_generation_defaults_to_latest_supported_generation():
    items = [
        ClaimItemInput(
            line_id="item_unknown_generation",
            input_name="급여 외래진료비",
            claimed_amount="100000",
            user_category_hint="급여",
        )
    ]
    context = ClaimCaseContext(policy_generation="6th", visit_type="outpatient")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.policy_generation == "5th"
    assert result.deductible == "20000"
    assert result.payable_amount == "80000"

@pytest.mark.parametrize(
    ("generation", "expected_deductible", "expected_payable"),
    [
        ("4th", "20000", "80000"),
        ("5th", "20000", "80000"),
    ],
)
def test_generation_same_result_for_outpatient_covered_benefit(generation: str, expected_deductible: str, expected_payable: str):
    """급여 통원 청구는 4세대와 5세대 모두 20% 공제 기준으로 같은 결과가 나와야 한다."""
    items = [ClaimItemInput(line_id="line_benefit", input_name="급여 외래진료비", claimed_amount="100000", user_category_hint="급여")]
    context = ClaimCaseContext(policy_generation=generation, visit_type="outpatient")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == expected_deductible
    assert result.payable_amount == expected_payable
    assert not result.requires_review


def test_claim_case_context_defaults_special_calculation_unknown():
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")

    assert context.special_calculation_status == "unknown"


def test_claim_case_context_accepts_case_level_special_calculation_status():
    context = ClaimCaseContext(
        policy_generation="5th",
        visit_type="hospitalization",
        special_calculation_status="not_applied",
    )

    assert context.special_calculation_status == "not_applied"


@pytest.mark.parametrize(
    ("generation", "expected_deductible", "expected_payable"),
    [
        ("4th", "60000", "140000"),
        ("5th", "60000", "140000"),
    ],
)
def test_generation_same_result_for_severe_nonpay(generation: str, expected_deductible: str, expected_payable: str):
    """5세대 중증 비급여는 기존 4세대 비급여와 같이 30% 공제 기준으로 계산된다."""
    items = [ClaimItemInput(line_id="line_severe", input_name="산정특례 중증 비급여 치료", claimed_amount="200000", user_category_hint="중증비급여")]
    context = ClaimCaseContext(policy_generation=generation, visit_type="outpatient")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == expected_deductible
    assert result.payable_amount == expected_payable
    assert not result.requires_review


def test_generation_difference_for_nonsevere_nonpay():
    """비중증 비급여는 4세대 30%, 5세대 50% 공제로 서로 다른 지급예상액이 산출되어야 한다."""
    items = [ClaimItemInput(line_id="line_nonsevere", input_name="비중증 비급여 주사료", claimed_amount="200000", user_category_hint="비중증비급여")]

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        fourth = run_claim_calculation(None, items, ClaimCaseContext(policy_generation="4th", visit_type="outpatient"), use_fake_planner=True)
    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        fifth = run_claim_calculation(None, items, ClaimCaseContext(policy_generation="5th", visit_type="outpatient"), use_fake_planner=True)

    assert fourth.deductible == "60000"
    assert fourth.payable_amount == "140000"
    assert fifth.deductible == "100000"
    assert fifth.payable_amount == "100000"


def test_fifth_generation_unknown_three_major_nonpay_requires_special_status():
    """5세대 3대비급여는 산정특례 여부가 모호하면 자동 지급 산정하지 않는다."""
    items = [ClaimItemInput(line_id="line_dosu", input_name="도수치료", claimed_amount="100000", user_category_hint="3대비급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", special_calculation_status="unknown")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == "0"
    assert result.payable_amount == "0"
    assert result.requires_review
    assert result.line_results[0]["calculation_status"] == "human_task"
    assert result.line_results[0]["excluded_from_calculation"] is True
    assert any("산정특례 적용 여부" in reason for reason in result.line_results[0]["review_reasons"])


def test_fifth_generation_not_applied_manual_therapy_is_not_auto_paid():
    """5세대 산정특례 미적용의 도수치료는 자동 지급 산정에서 제외한다."""
    items = [ClaimItemInput(line_id="line_dosu", input_name="도수치료", claimed_amount="100000", user_category_hint="3대비급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", special_calculation_status="not_applied")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == "0"
    assert result.payable_amount == "0"
    assert result.requires_review
    assert result.line_results[0]["calculation_status"] == "human_task"
    assert result.line_results[0]["human_task_amount"] == "100000"
    assert any("산정특례 미적용" in reason for reason in result.line_results[0]["review_reasons"])


def test_fifth_generation_not_applied_mri_waits_for_approved_rule():
    """MRI/MRA 전용 active rule이 없으면 기존 급여 fallback으로 자동 계산하지 않는다."""
    items = [ClaimItemInput(line_id="line_mri", input_name="MRI 자기공명영상진단", claimed_amount="100000", user_category_hint="3대비급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", special_calculation_status="not_applied")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == "0"
    assert result.payable_amount == "0"
    assert result.line_results[0]["calculation_status"] == "human_task"
    assert any("전용 계산 rule" in reason for reason in result.line_results[0]["review_reasons"])


def test_fifth_generation_applied_three_major_nonpay_uses_special_case_rule():
    """5세대 산정특례 적용 3대비급여는 승인된 중증비급여 rule 경로로 계산한다."""
    items = [ClaimItemInput(line_id="line_dosu", input_name="도수치료", claimed_amount="100000", user_category_hint="3대비급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", special_calculation_status="applied")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == "30000"
    assert result.payable_amount == "70000"
    assert "중증비급여" in result.line_results[0]["category"]


def test_grouped_deductible_applies_once_for_same_fifth_benefit_outpatient_group():
    """동일 공제 그룹의 급여 통원 항목은 합산 금액에 대해 한 번 공제한다."""
    items = [
        ClaimItemInput(line_id="line_1", input_name="급여 외래진료비 A", claimed_amount="30000", user_category_hint="급여"),
        ClaimItemInput(line_id="line_2", input_name="급여 외래진료비 B", claimed_amount="30000", user_category_hint="급여"),
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", facility_grade="clinic")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.claimed_amount == "60000"
    assert result.deductible == "12000"
    assert result.payable_amount == "48000"
    assert sum(int(line["deductible"]) for line in result.line_results) == 12000
    assert all(line["deductible_group"] == "benefit_group" for line in result.line_results)


def test_grouped_deductible_excludes_human_task_lines_from_group_amount():
    """자동 산정 제외 항목은 동일 공제 그룹 합산에서 제외한다."""
    items = [
        ClaimItemInput(line_id="line_1", input_name="급여 외래진료비", claimed_amount="30000", user_category_hint="급여"),
        ClaimItemInput(line_id="line_2", input_name="도수치료", claimed_amount="100000", user_category_hint="3대비급여"),
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", facility_grade="clinic", special_calculation_status="unknown")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == "10000"
    assert result.payable_amount == "20000"
    assert result.line_results[1]["calculation_status"] == "human_task"
    assert result.line_results[1]["deductible_group"] == ""


def test_excluded_standard_opinion_forces_zero_payable():
    """표준모델 보상의견이 면책이면 일반 공제 산식 대신 지급예상액 0원으로 처리한다."""
    items = [ClaimItemInput(line_id="line_excluded", input_name="도수치료", claimed_amount="100000")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")
    mock_match = {
        "std_cd": "51040",
        "std_cd_nm": "도수치료",
        "mid_category_cd_nm": "공상",
        "ins_care_type_cd_nm": "급여",
        "pay_opn_cd_nm": "면책",
    }

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == "100000"
    assert result.payable_amount == "0"
    assert result.requires_review
    assert "면책" in result.line_results[0]["rule_summary"]
    assert any("지급예상액을 0원" in reason for reason in result.review_reasons)


def test_split_receipt_l1213_covers_insured_copay_even_when_nonpay_unavailable():
    """급여외 산정불가 표준모델 의견은 비급여 금액에 적용하고 급여 본인부담금은 보상 계산한다."""
    items = [
        ClaimItemInput(
            line_id="line_l1213",
            input_name="마취료",
            input_code="L1213",
            insured_copay_amount="23434",
            nonpay_amount="0",
            quantity="1",
            user_category_hint="급여",
            extra_info="입원 중 수술 마취",
        )
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="hospitalization")
    mock_match = {
        "std_cd": "L1213",
        "std_cd_nm": "척추마취관리기본[1시간기준]",
        "mid_category_cd_nm": "마취료",
        "hira_care_type_cd_nm": "급여",
        "ins_care_type_cd_nm": "급여",
        "medical_class_cd_nm": "입원",
        "item_class_level1cd_nm": "마취료",
        "item_class_level2cd_nm": "척추마취",
        "pay_opn_cd_nm": "급여외 산정불가",
    }

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=mock_match):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.claimed_amount == "23434"
    assert result.payable_amount == "18747"
    assert result.deductible == "4687"
    assert result.line_results[0]["insured_copay_amount"] == "23434"
    assert result.line_results[0]["nonpay_amount"] == "0"
    assert "급여 본인부담금" in result.line_results[0]["rule_summary"]
    assert "급여외 산정불가" in result.applied_basis[0]["content"]


def test_split_receipt_standard_opinion_excludes_only_nonpay_part():
    """분리 입력에서는 표준모델의 비급여 산정 제한이 급여 본인부담금까지 0원 처리하지 않는다."""
    items = [
        ClaimItemInput(
            line_id="line_split",
            input_name="마취료",
            input_code="L1213",
            insured_copay_amount="10000",
            nonpay_amount="50000",
            quantity="1",
            user_category_hint="급여",
        )
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="hospitalization")
    mock_match = {
        "std_cd": "L1213",
        "std_cd_nm": "척추마취관리기본[1시간기준]",
        "mid_category_cd_nm": "마취료",
        "hira_care_type_cd_nm": "급여",
        "ins_care_type_cd_nm": "급여",
        "pay_opn_cd_nm": "급여외 산정불가",
    }

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=mock_match):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.claimed_amount == "60000"
    assert result.payable_amount == "8000"
    assert result.deductible == "52000"
    assert result.requires_review
    assert any("급여외/비급여 산정 제한" in reason for reason in result.review_reasons)
    assert result.applied_basis[0]["review_status"] == "review_required"


def test_fifth_generation_unresolved_split_nonpay_is_human_task_excluded_from_totals():
    """5세대 미분류 비급여는 자동 지급/공제 합계에서 제외하고 Human Task로 분리한다."""
    items = [
        ClaimItemInput(line_id="line_benefit", input_name="급여 입원 본인부담금", insured_copay_amount="10000", nonpay_amount="0", quantity="1", user_category_hint="급여"),
        ClaimItemInput(line_id="line_unknown_nonpay", input_name="메가디쓰리정 25000IU 비타민D", input_code="659901271", insured_copay_amount="0", nonpay_amount="48000", quantity="1", user_category_hint=""),
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="hospitalization")
    matches = [
        [{"std_cd": "PAY001", "std_cd_nm": "급여 입원 본인부담금", "mid_category_cd_nm": "급여", "hira_care_type_cd_nm": "급여", "ins_care_type_cd_nm": "급여", "pay_opn_cd_nm": "보상"}],
        [],
    ]

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=None), patch("src.db.standard_codes.search_by_name", side_effect=matches):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.claimed_amount == "58000"
    assert result.payable_amount == "8000"
    assert result.deductible == "2000"
    assert result.requires_review
    human_task_line = result.line_results[1]
    assert human_task_line["category"] == "미분류 비급여"
    assert human_task_line["payable_amount"] == "0"
    assert human_task_line["deductible"] == "0"
    assert human_task_line["calculation_status"] == "human_task"
    assert human_task_line["excluded_from_calculation"] is True
    assert any("Human Task" in reason for reason in result.review_reasons)


def test_fourth_generation_unresolved_split_nonpay_is_human_task_excluded_from_totals():
    """4세대에서도 미분류 비급여는 자동 지급/공제 합계에서 제외하고 Human Task로 분리한다."""
    items = [
        ClaimItemInput(line_id="line_benefit", input_name="급여 입원 본인부담금", insured_copay_amount="10000", nonpay_amount="0", quantity="1", user_category_hint="급여"),
        ClaimItemInput(line_id="line_unknown_nonpay", input_name="미분류 비급여 치료재료", insured_copay_amount="0", nonpay_amount="48000", quantity="1", user_category_hint=""),
    ]
    context = ClaimCaseContext(policy_generation="4th", visit_type="hospitalization")

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=None), patch("src.db.standard_codes.search_by_name", return_value=[]):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.claimed_amount == "58000"
    assert result.payable_amount == "8000"
    assert result.deductible == "2000"
    human_task_line = result.line_results[1]
    assert human_task_line["category"] == "미분류 비급여"
    assert human_task_line["payable_amount"] == "0"
    assert human_task_line["deductible"] == "0"
    assert human_task_line["calculation_status"] == "human_task"
    assert human_task_line["excluded_from_calculation"] is True


def test_matched_general_nonpay_with_clear_opinion_is_still_calculated():
    """표준모델 보상의견이 명확한 비급여는 세대 공통 Human Task 제외 대상이 아니다."""
    items = [ClaimItemInput(line_id="line_matched_nonpay", input_name="명확한 비급여 항목", claimed_amount="100000", quantity="1")]
    context = ClaimCaseContext(policy_generation="4th", visit_type="hospitalization")
    mock_match = {"std_cd": "NP001", "std_cd_nm": "명확한 비급여 항목", "mid_category_cd_nm": "비급여", "ins_care_type_cd_nm": "비급여", "pay_opn_cd_nm": "보상"}

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.payable_amount == "70000"
    assert result.deductible == "30000"
    assert result.line_results[0]["category"] == "비급여"
    assert result.line_results[0]["calculation_status"] == "calculated"


def test_coordination_review_does_not_leak_without_explicit_signal():
    """자동차/산재 맥락이 없는 청구에는 중복보상 조정 review reason이 붙지 않아야 한다."""
    from src.graph.retriever import GraphRetrievalResult, GraphReviewPath

    items = [ClaimItemInput(line_id="line_excluded", input_name="도수치료", claimed_amount="100000")]
    context = ClaimCaseContext(
        policy_generation="5th",
        visit_type="outpatient",
        coverage_topic="실손, 3대비급여",
    )
    mock_match = {
        "std_cd": "51040",
        "std_cd_nm": "도수치료",
        "mid_category_cd_nm": "공상",
        "ins_care_type_cd_nm": "급여",
        "pay_opn_cd_nm": "면책",
    }

    mock_graph_result = MagicMock(spec=GraphRetrievalResult)
    mock_graph_result.facts = []
    mock_graph_result.review_paths = [
        GraphReviewPath(
            path_id="condition::dosu",
            path_type="claim_condition_review",
            status="review_required",
            summary="문서 기반 보장 주제/판단 조건 검토 경로를 수집했습니다.",
            coordination_rules=["산재보험 처리 후 실손 청구"],
        )
    ]

    mock_rag = MagicMock()
    mock_rag.graph_enabled = True
    mock_rag.graph_retriever = MagicMock()
    mock_rag.graph_retriever.retrieve.return_value = mock_graph_result

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(
            rag_pipeline=mock_rag,
            items=items,
            context=context,
            use_fake_planner=True,
        )

    assert not any("중복 보상 조정 검토" in reason for reason in result.review_reasons)
    assert result.coordination_rules == []
    assert not any("GraphDB ReviewPath" in basis["source"] for basis in result.applied_basis)


def test_review_path_guidance_does_not_pollute_applied_basis():
    """검토 경로 요약은 review reason에는 남아도 적용 근거 목록에는 직접 섞이지 않아야 한다."""
    from src.graph.retriever import GraphRetrievalResult, GraphReviewPath

    items = [ClaimItemInput(line_id="line_reviewpath", input_name="도수치료", claimed_amount="100000")]
    context = ClaimCaseContext(
        policy_generation="5th",
        visit_type="outpatient",
        coverage_topic="실손, 3대비급여",
    )
    mock_match = {
        "std_cd": "51040",
        "std_cd_nm": "도수치료",
        "mid_category_cd_nm": "공상",
        "ins_care_type_cd_nm": "급여",
        "pay_opn_cd_nm": "면책",
    }

    mock_graph_result = MagicMock(spec=GraphRetrievalResult)
    mock_graph_result.facts = []
    mock_graph_result.review_paths = [
        GraphReviewPath(
            path_id="condition::dosu",
            path_type="claim_condition_review",
            status="review_required",
            summary="문서 기반 보장 주제/판단 조건 검토 경로를 수집했습니다.",
            review_actions=["진단서 요청"],
        )
    ]

    mock_rag = MagicMock()
    mock_rag.graph_enabled = True
    mock_rag.graph_retriever = MagicMock()
    mock_rag.graph_retriever.retrieve.return_value = mock_graph_result

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(
            rag_pipeline=mock_rag,
            items=items,
            context=context,
            use_fake_planner=True,
        )

    assert any("권장 검토 조치: 진단서 요청" in reason for reason in result.review_reasons)
    assert not any("GraphDB ReviewPath" in basis["source"] for basis in result.applied_basis)


def test_excluded_standard_opinion_blocks_llm_formula(monkeypatch):
    """LLM 경로에서도 표준모델 면책 의견은 일반 산식보다 우선되어 0원 처리된다."""
    items = [ClaimItemInput(line_id="line_excluded_llm", input_name="도수치료", input_code="51040", claimed_amount="100000")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")
    mock_match = {
        "std_cd": "51040",
        "std_cd_nm": "도수치료",
        "mid_category_cd_nm": "공상",
        "ins_care_type_cd_nm": "급여",
        "pay_opn_cd_nm": "면책",
    }

    class WrongLLM:
        def generate(self, *_args, **_kwargs) -> str:
            raise AssertionError("면책 표준모델은 LLM 계산 경로를 호출하지 않아야 한다.")

    monkeypatch.setattr("src.claim_calculation.planner.build_llm", lambda *_args, **_kwargs: WrongLLM())

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=mock_match):
        result = run_claim_calculation(None, items, context, use_fake_planner=False, provider="vllm", model_id="local-test")

    assert result.deductible == "100000"
    assert result.payable_amount == "0"
    assert result.requires_review
    assert result.line_results[0]["payable_amount"] == "0"


def test_llm_wrong_fifth_generation_formula_is_overridden_by_deterministic_guard(monkeypatch):
    """LLM이 5세대 비중증 비급여 공제율을 잘못 내도 결정론 기준으로 최종값을 보호한다."""
    items = [ClaimItemInput(line_id="line_guard", input_name="비중증 비급여 주사료", claimed_amount="200000", user_category_hint="비중증비급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")

    class WrongFormulaLLM:
        def generate(self, *_args, **_kwargs) -> str:
            formula = (
                "from decimal import Decimal\n"
                "claimed_amount = Decimal('200000')\n"
                "deductible = max(Decimal('30000'), claimed_amount * Decimal('0.3'))\n"
                "payable_amount = claimed_amount - deductible"
            )
            escaped = formula.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
            return (
                "{"
                '"decision":"calculable",'
                '"basis_summary":[{"source":"테스트","content":"잘못된 30% 산식"}],'
                '"variables":{},'
                '"calculation_steps":["잘못된 산식"],'
                f'"formula_intent":"{escaped}",'
                '"uncertainties":[]'
                "}"
            )

    monkeypatch.setattr("src.claim_calculation.planner.build_llm", lambda *_args, **_kwargs: WrongFormulaLLM())

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=False, provider="vllm", model_id="local-test")

    assert result.deductible == "100000"
    assert result.payable_amount == "100000"
    assert result.requires_review
    assert any("결정론 계산값" in reason for reason in result.review_reasons)
    assert "from decimal import Decimal" not in result.executed_code


def test_llm_not_covered_decision_without_rule_evidence_is_review_only(monkeypatch):
    """LLM 단독 면책 판단은 최종 지급거절 근거가 아니며 rule layer 계산값을 유지한다."""
    items = [ClaimItemInput(line_id="line_llm_not_covered", input_name="급여 통원 치료비", claimed_amount="100000", user_category_hint="급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")

    class WrongDecisionLLM:
        def generate(self, *_args, **_kwargs) -> str:
            return (
                "{"
                '"decision":"not_covered",'
                '"basis_summary":[{"source":"LLM 추정","content":"근거 없이 면책"}],'
                '"variables":{},'
                '"calculation_steps":["면책으로 판단"],'
                '"formula_intent":"",'
                '"uncertainties":["근거 부족"]'
                "}"
            )

    monkeypatch.setattr("src.claim_calculation.planner.build_llm", lambda *_args, **_kwargs: WrongDecisionLLM())

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=False, provider="vllm", model_id="local-test")

    assert result.payable_amount == "80000"
    assert result.deductible == "20000"
    assert result.calculation_status == "blocked_missing_info"
    assert any("LLM 단독 면책 판단" in reason for reason in result.review_reasons)


@pytest.mark.parametrize(
    ("generation", "category", "claimed", "expected_deductible", "expected_payable"),
    [
        ("4th", "급여", "30000", "10000", "20000"),
        ("4th", "비급여", "50000", "30000", "20000"),
        ("5th", "비중증비급여", "50000", "50000", "0"),
    ],
)
def test_minimum_deductible_boundaries(generation: str, category: str, claimed: str, expected_deductible: str, expected_payable: str):
    """통원 최소공제금액이 비율공제보다 클 때 최소공제금액을 적용한다."""
    items = [ClaimItemInput(line_id="line_min", input_name=f"{category} 통원료", claimed_amount=claimed, user_category_hint=category)]
    context = ClaimCaseContext(policy_generation=generation, visit_type="outpatient")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == expected_deductible
    assert result.payable_amount == expected_payable


def test_upper_room_charge_difference_special_rule_caps_daily_average():
    """상급병실료 차액은 1일 평균 10만원 한도와 50% 보상 특례를 적용한다."""
    items = [
        ClaimItemInput(
            line_id="line_room",
            input_name="상급병실료 차액",
            claimed_amount="150000",
            quantity="2",
            user_category_hint="비급여",
        )
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="hospitalization")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.claimed_amount == "300000"
    assert result.payable_amount == "100000"
    assert result.deductible == "200000"
    assert result.line_results[0]["rule_summary"].startswith("상급병실료 차액 특례")


def test_upper_room_charge_difference_ignores_stale_exclusion_code_match():
    """상급병실료 차액은 잘못 남은 표준코드가 있어도 이름 기반 특례 규칙을 우선 적용해야 한다."""
    items = [
        ClaimItemInput(
            line_id="line_room",
            input_name="상급병실료 차액",
            input_code="51040",
            claimed_amount="150000",
            quantity="2",
        )
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="hospitalization")

    stale_match_row = {
        "std_cd": "51040",
        "std_cd_nm": "도수치료",
        "mid_category_cd_nm": "비급여",
        "pay_opn_cd_nm": "면책",
    }

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=stale_match_row), patch(
        "src.db.standard_codes.search_by_name",
        return_value=[stale_match_row],
    ):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.claimed_amount == "300000"
    assert result.payable_amount == "100000"
    assert result.deductible == "200000"
    assert result.line_results[0]["rule_summary"].startswith("상급병실료 차액 특례")


def test_health_insurance_unapplied_special_case_uses_40_percent_after_deductible():
    """건강보험/의료급여 미적용 특례는 통원 공제 후 금액의 40%만 보상하고 검토 플래그를 세운다."""
    items = [ClaimItemInput(line_id="line_unapplied", input_name="급여 통원 치료비", claimed_amount="100000", user_category_hint="급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", situation_note="건강보험 미적용으로 요양급여를 적용받지 못한 건")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.payable_amount == "32000"
    assert result.deductible == "68000"
    assert result.requires_review
    assert any("40% 특례" in reason or "40%" in result.line_results[0]["rule_summary"] for reason in result.review_reasons)


def test_mixed_receipt_line_items_total_like_medical_bill_detail():
    """진료비 영수증과 세부내역서처럼 급여/비급여/상급병실료가 섞인 청구 건을 항목별 합산한다."""
    items = [
        ClaimItemInput(line_id="line_pay", input_name="급여 입원 본인부담금", claimed_amount="400000", user_category_hint="급여"),
        ClaimItemInput(line_id="line_nonpay", input_name="비중증 비급여 처치료", claimed_amount="300000", user_category_hint="비중증비급여"),
        ClaimItemInput(line_id="line_room", input_name="상급병실료 차액", claimed_amount="120000", quantity="3", user_category_hint="비급여"),
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="hospitalization")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.claimed_amount == "1060000"
    assert result.deductible == "440000"
    assert result.payable_amount == "620000"
    assert [line["payable_amount"] for line in result.line_results] == ["320000", "150000", "150000"]


@pytest.mark.parametrize(
    (
        "case_name",
        "items",
        "context",
        "formula",
        "expected_claimed",
        "expected_deductible",
        "expected_payable",
    ),
    [
        (
            "4th_nonpay_outpatient",
            [ClaimItemInput(line_id="line_nonpay_4th", input_name="비급여 주사료", claimed_amount="200000", user_category_hint="비급여")],
            ClaimCaseContext(policy_generation="4th", visit_type="outpatient"),
            "claimed_amount = Decimal('200000')\n"
            "deductible = max(Decimal('30000'), claimed_amount * Decimal('0.3'))\n"
            "payable_amount = claimed_amount - deductible",
            "200000",
            "60000",
            "140000",
        ),
        (
            "5th_nonsevere_nonpay_outpatient",
            [ClaimItemInput(line_id="line_nonpay_5th", input_name="비중증 비급여 주사료", claimed_amount="200000", user_category_hint="비중증비급여")],
            ClaimCaseContext(policy_generation="5th", visit_type="outpatient"),
            "claimed_amount = Decimal('200000')\n"
            "deductible = max(Decimal('50000'), claimed_amount * Decimal('0.5'))\n"
            "payable_amount = claimed_amount - deductible",
            "200000",
            "100000",
            "100000",
        ),
        (
            "upper_room_difference_cap",
            [ClaimItemInput(line_id="line_room", input_name="상급병실료 차액", claimed_amount="120000", quantity="3", user_category_hint="비급여")],
            ClaimCaseContext(policy_generation="5th", visit_type="hospitalization"),
            "claimed_amount = Decimal('120000') * Decimal('3')\n"
            "daily_payable_base = min(Decimal('120000'), Decimal('100000'))\n"
            "payable_amount = daily_payable_base * Decimal('3') * Decimal('0.5')\n"
            "deductible = claimed_amount - payable_amount",
            "360000",
            "210000",
            "150000",
        ),
        (
            "health_insurance_unapplied_40_percent",
            [ClaimItemInput(line_id="line_unapplied", input_name="급여 통원 치료비", claimed_amount="100000", user_category_hint="급여")],
            ClaimCaseContext(policy_generation="5th", visit_type="outpatient", situation_note="건강보험 미적용으로 요양급여를 적용받지 못한 건"),
            "claimed_amount = Decimal('100000')\n"
            "base_deductible = max(Decimal('10000'), claimed_amount * Decimal('0.2'))\n"
            "base_after_deductible = claimed_amount - base_deductible\n"
            "payable_amount = base_after_deductible * Decimal('0.4')\n"
            "deductible = claimed_amount - payable_amount",
            "100000",
            "68000",
            "32000",
        ),
    ],
)
def test_llm_generated_formula_variants_do_not_override_rule_layer(
    monkeypatch,
    case_name: str,
    items: list[ClaimItemInput],
    context: ClaimCaseContext,
    formula: str,
    expected_claimed: str,
    expected_deductible: str,
    expected_payable: str,
):
    """LLM이 생성한 계산 코드는 최종 계산 권한이 아니며 rule layer 결과가 유지된다."""

    class FormulaLLM:
        def generate(self, prompt: str, temperature: float = 0.0) -> str:
            assert case_name in prompt or items[0].input_name in prompt
            escaped_formula = formula.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
            return (
                "{"
                '"decision":"calculable",'
                '"basis_summary":[{"source":"테스트 약관","content":"계산식 검증"}],'
                '"variables":{"case":"' + case_name + '"},'
                '"calculation_steps":["계산 코드 실행"],'
                '"formula_intent":"' + escaped_formula + '",'
                '"uncertainties":[]'
                "}"
            )

    monkeypatch.setattr("src.claim_calculation.planner.build_llm", lambda *_args, **_kwargs: FormulaLLM())

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=False, provider="vllm", model_id="local-test")

    assert result.claimed_amount == expected_claimed
    assert result.deductible == expected_deductible
    assert result.payable_amount == expected_payable
    assert result.executed_code != formula
    assert "claimed_amount = Decimal" in result.executed_code
    assert "Decimal" in result.executed_code
    assert any("LLM 산식은 최종 계산 권한이 아니므로" in reason for reason in result.review_reasons)


def test_pipeline_multi_line_claim_totals_by_generation():
    """진료비 영수증/세부내역서처럼 여러 청구 항목을 한 번의 청구 건으로 합산 계산한다."""
    items = [
        ClaimItemInput(
            line_id="line_1",
            input_name="급여 진료비",
            claimed_amount="100000",
            quantity="1",
            user_category_hint="급여",
        ),
        ClaimItemInput(
            line_id="line_2",
            input_name="비급여 주사료",
            claimed_amount="200000",
            quantity="1",
            user_category_hint="비중증비급여",
        ),
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")

    mock_matches = [
        {"std_cd": "PAY001", "std_cd_nm": "급여 진료비", "mid_category_cd_nm": "급여", "pay_opn_cd_nm": "보상"},
        {"std_cd": "NP001", "std_cd_nm": "비급여 주사료", "mid_category_cd_nm": "비급여", "pay_opn_cd_nm": "보상"},
    ]

    with patch("src.db.standard_codes.search_by_name", side_effect=[[mock_matches[0]], [mock_matches[1]]]):
        result = run_claim_calculation(
            rag_pipeline=None,
            items=items,
            context=context,
            use_fake_planner=True,
        )

    assert result.claimed_amount == "300000"
    assert result.deductible == "120000"
    assert result.payable_amount == "180000"
    assert result.policy_generation == "5th"
    assert len(result.line_results) == 2
    assert result.line_results[0]["deductible"] == "20000"
    assert result.line_results[1]["deductible"] == "100000"
    assert not result.requires_review


def test_pipeline_not_covered():
    """보상 제외(not_covered) 시나리오에서 지급예상액이 0원이고 추가 검토 플래그가 활성화되는지 검증한다."""
    items = [
        ClaimItemInput(
            line_id="item_2",
            input_name="도수치료 제외",
            claimed_amount="150000"
        )
    ]
    context = ClaimCaseContext()

    mock_match = {
        "std_cd": "SC0001",
        "std_cd_nm": "도수치료",
        "pay_opn_cd_nm": "보상",
    }

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(
            rag_pipeline=None,
            items=items,
            context=context,
            use_fake_planner=True
        )

        assert result.payable_amount == "0"
        assert result.requires_review
        assert any("보상 대상" in reason or "면책" in reason for reason in result.review_reasons)


def test_pipeline_needs_more_info():
    """정보 부족(needs_more_info) 시나리오에서 추가 검토 플래그가 활성화되는지 검증한다."""
    items = [
        ClaimItemInput(
            line_id="item_3",
            input_name="정보부족 항목",
            claimed_amount="80000"
        )
    ]
    context = ClaimCaseContext()

    mock_match = {
        "std_cd": "SC0005",
        "std_cd_nm": "정보부족 항목",
        "pay_opn_cd_nm": "보상",
    }

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(
            rag_pipeline=None,
            items=items,
            context=context,
            use_fake_planner=True
        )

        assert result.requires_review
        assert any("정보가 부족" in reason for reason in result.review_reasons)


def test_pipeline_deterministic_default_prevents_over_claimed_warning():
    """기본 결정론 계산 경로는 지급예상액이 청구액을 초과하지 않도록 항목별 공제를 적용한다."""
    items = [
        ClaimItemInput(
            line_id="item_4",
            input_name="일반 시술",
            claimed_amount="50000"
        )
    ]
    context = ClaimCaseContext()

    mock_match = {
        "std_cd": "SC0006",
        "std_cd_nm": "일반 시술",
        "pay_opn_cd_nm": "보상",
    }

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(
            rag_pipeline=None,
            items=items,
            context=context,
            use_fake_planner=True
        )

        assert result.payable_amount == "40000"
        assert result.deductible == "10000"
        assert result.requires_review
        assert any("급여/비급여/중증" in reason for reason in result.review_reasons)


def test_pipeline_formatted_amount_parsing():
    """150000, 150,000, 150,000원 케이스 등 포맷팅된 청구금액 문자열이 주어졌을 때도 파이프라인과 FakePlanner가 오류 없이 동작하는지 검증한다."""
    mock_match = {
        "std_cd": "SC0001",
        "std_cd_nm": "도수치료",
        "mid_category_cd_nm": "물리치료",
        "pay_opn_cd_nm": "보상",
    }

    test_cases = ["150000", "150,000", "150,000원", " 150,000 원 "]

    for claimed in test_cases:
        items = [
            ClaimItemInput(
                line_id="item_format_test",
                input_name="도수치료",
                claimed_amount=claimed,
                quantity="1"
            )
        ]
        context = ClaimCaseContext(
            situation_note="도수치료 금액 포맷 테스트",
            visit_type="outpatient"
        )

        with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
            result = run_claim_calculation(
                rag_pipeline=None,
                items=items,
                context=context,
                use_fake_planner=True
            )
            assert result.claimed_amount == "150000"
            assert result.payable_amount == "0"
            assert result.deductible == "0"
            assert result.line_results[0]["calculation_status"] == "human_task"
            assert result.requires_review


def test_pipeline_multiple_candidates_populate():
    """복수 표준코드 후보는 후보를 노출하되 첫 번째 후보로 임의 계산하지 않는다."""
    items = [
        ClaimItemInput(
            line_id="item_multi_test",
            input_name="도수치료",
            claimed_amount="150000"
        )
    ]
    context = ClaimCaseContext()

    # standard_codes.search_by_name은 dict 리스트를 반환하므로 dict 형태로 정의
    mock_matches = [
        {"std_cd": "SC0001", "std_cd_nm": "도수치료", "mid_category_cd_nm": "물리치료", "pay_opn_cd_nm": "보상"},
        {"std_cd": "MX122", "std_cd_nm": "도수치료-기타", "mid_category_cd_nm": "물리치료", "pay_opn_cd_nm": "보상"},
    ]

    with patch("src.db.standard_codes.search_by_name", return_value=mock_matches):
        result = run_claim_calculation(
            rag_pipeline=None,
            items=items,
            context=context,
            use_fake_planner=True
        )

        assert result.requires_review
        assert result.payable_amount == "0"
        assert result.deductible == "0"
        assert result.calculation_status == "blocked_missing_info"
        assert result.notes == "표준코드 선택 전 산정 보류"
        assert len(result.candidates) == 2
        assert result.candidates[0]["code"] == "SC0001"
        assert result.candidates[1]["code"] == "MX122"
        assert result.line_results[0]["rule_summary"] == "표준코드 선택 전 산정 보류"
        assert result.line_results[0]["calculation_status"] == "needs_code_selection"
        assert result.line_results[0]["excluded_from_calculation"] is True
        assert result.line_results[0]["deductible"] is None
        assert result.line_results[0]["deductible_amount"] is None
        assert result.line_results[0]["payable_amount"] is None
        assert len(result.line_results[0]["candidates"]) == 2


def _manual_therapy_standard_rows() -> list[dict[str, str]]:
    return [
        {
            "std_cd": "51040",
            "std_cd_nm": "도수치료",
            "mid_category_cd_nm": "물리치료",
            "ins_care_type_cd_nm": "급여",
            "pay_opn_cd_nm": "면책",
            "notes": "급여외 산정불가",
        },
        {
            "std_cd": "MX122",
            "std_cd_nm": "도수치료 [1일당]",
            "mid_category_cd_nm": "물리치료",
            "ins_care_type_cd_nm": "비급여_특약1",
            "pay_opn_cd_nm": "추가확인",
        },
    ]


def test_fourth_nonpay_manual_therapy_uses_mx122_with_active_exact_rule():
    """비급여 금액 범위는 MX122를 선택하고 승인된 전용 룰로 산정한다."""
    items = [
        ClaimItemInput(
            line_id="manual-nonpay",
            input_name="도수치료",
            insured_copay_amount="0",
            nonpay_amount="500000",
        )
    ]
    context = ClaimCaseContext(policy_generation="4th", visit_type="outpatient")

    with patch("src.db.standard_codes.search_by_name", return_value=_manual_therapy_standard_rows()):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.calculation_status == "estimated_review_required"
    assert result.deductible == "150000"
    assert result.payable_amount == "350000"
    assert result.line_results[0]["category"] == "3대비급여_도수"
    assert result.line_results[0]["excluded_from_calculation"] is False
    assert any("누적 청구 이력이 없어 승인 룰의 연간 한도" in reason for reason in result.line_results[0]["review_reasons"])
    assert any("최초 10회 이후" in reason for reason in result.line_results[0]["review_reasons"])
    assert any("MX122" in basis["source"] for basis in result.applied_basis)


def test_fourth_nonpay_manual_therapy_explicit_51040_keeps_exclusion_outcome():
    """직접 입력한 급여/면책 표준코드는 범위와 다르더라도 정확코드 근거를 보존한다."""
    items = [
        ClaimItemInput(
            line_id="manual-explicit",
            input_name="도수치료",
            input_code="51040",
            insured_copay_amount="0",
            nonpay_amount="500000",
        )
    ]
    context = ClaimCaseContext(policy_generation="4th", visit_type="outpatient")

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=_manual_therapy_standard_rows()[0]):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.payable_amount == "0"
    assert result.deductible == "500000"
    assert any("입력 표준코드" in reason for reason in result.review_reasons)


def test_fourth_manual_therapy_approved_temp_rule_estimates_350k(monkeypatch, tmp_path):
    """승인된 전용 manifest에서만 50만원 비급여 도수치료를 계산한다."""
    from src.claim_calculation import deductible_rules

    manifest = tmp_path / "claim_deductible_rules.active.json"
    manifest.write_text(
        '''{
          "version": 1,
          "rules": [{
            "rule_id": "deductible.4th.three_major_manual.outpatient",
            "generation": "4th", "category": "3대비급여_도수", "visit_type": "outpatient",
            "facility_grade": "all", "copay_ratio": "0.3", "min_deductible": "30000",
            "min_deductible_by_facility": {"clinic": "30000", "hospital": "30000", "general_hospital": "30000", "tertiary_hospital": "30000"},
            "per_visit_limit": null, "annual_limit": "3500000", "annual_visit_limit": 50,
            "review_requirements": ["최초 10회 이후 증상 호전 증빙 확인 필요"],
            "description": "4세대 도수치료군: 1회당 3만원과 보장대상의료비 30% 중 큰 금액, 연 350만원·50회",
            "source_doc": "약관", "source_page": "71-78", "source_clause": "제3조 보장종목별 보상내용 / 3대비급여 특별약관",
            "source_chunk_id": "약관_ch_002441", "approval_status": "active", "source_status": "source_grounded"
          }],
          "prescription_rules": [], "special_rules": []
        }''',
        encoding="utf-8",
    )
    monkeypatch.setattr(deductible_rules, "CLAIM_RULES_PATH", manifest)
    deductible_rules._load_registry.cache_clear()
    items = [
        ClaimItemInput(
            line_id="manual-approved",
            input_name="도수치료",
            input_code="MX122",
            insured_copay_amount="0",
            nonpay_amount="500000",
        )
    ]
    context = ClaimCaseContext(policy_generation="4th", visit_type="outpatient")
    try:
        with patch("src.db.standard_codes.lookup_by_std_cd", return_value=_manual_therapy_standard_rows()[1]):
            result = run_claim_calculation(None, items, context, use_fake_planner=True)
    finally:
        deductible_rules._load_registry.cache_clear()

    assert result.deductible == "150000"
    assert result.payable_amount == "350000"
    assert result.calculation_status == "estimated_review_required"
    assert any("3500000" in reason.replace(",", "") or "350만원" in reason for reason in result.review_reasons)
    assert any("최초 10회 이후" in reason for reason in result.review_reasons)


def test_pipeline_mri_does_not_match_unrelated_treatment_material():
    """MRI 질의가 MRI 가능 치료재료 행에 매칭되어 3대비급여 계산으로 오분류되지 않도록 한다."""
    items = [
        ClaimItemInput(
            line_id="item_mri",
            input_name="MRI",
            claimed_amount="100000",
            quantity="1",
        )
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")
    mock_matches = [
        {
            "std_cd": "TM001",
            "std_cd_nm": "MRI SURESCAN PACEMAKER",
            "mid_category_cd_nm": "말초신경자극술용 치료재료",
            "ins_care_type_cd_nm": "비급여",
            "pay_opn_cd_nm": "보상",
        },
        {
            "std_cd": "HE115",
            "std_cd_nm": "자기공명영상진단-복부",
            "mid_category_cd_nm": "방사선특수영상진단료",
            "ins_care_type_cd_nm": "비급여_특약3",
            "pay_opn_cd_nm": "보상",
        },
    ]

    with patch("src.db.standard_codes.search_by_name", return_value=mock_matches):
        result = run_claim_calculation(
            rag_pipeline=None,
            items=items,
            context=context,
            use_fake_planner=True,
        )

    assert result.payable_amount == "0"
    assert result.deductible == "0"
    assert result.line_results[0]["category"] == "비급여자기공명영상진단"
    assert result.line_results[0]["calculation_status"] == "human_task"
    assert any("산정특례 적용 여부" in reason for reason in result.review_reasons)
    assert "HE115" in result.applied_basis[0]["source"]
    assert "TM001" not in result.applied_basis[0]["source"]


def test_fake_planner_amount_formatting_variations():
    """FakePlanner는 포맷팅된 금액을 파싱하되 도메인 산식은 만들지 않는다."""
    from src.claim_calculation.planner import FakePlanner

    test_cases = ["150000", "150,000", "150,000원", " 150,000 원 "]
    planner = FakePlanner()

    for val in test_cases:
        items = [
            ClaimItemInput(
                line_id="test",
                input_name="도수치료",
                claimed_amount=val,
                quantity="1"
            )
        ]
        context = ClaimCaseContext()
        plan = planner.plan(items, context, [])
        assert plan.decision == "calculable"
        assert plan.variables["claimed_amount"] == "150000"
        assert plan.formula_intent == ""


def test_pipeline_confirmed_without_evidence_excluded():
    """confirmed fact에 evidence가 없으면 retrieved_evidences에서 배제되는지 검증한다."""
    items = [ClaimItemInput(line_id="item_1", input_name="테스트수술", claimed_amount="100000")]
    context = ClaimCaseContext()

    mock_match = {"std_cd": "SC0001", "std_cd_nm": "테스트수술", "pay_opn_cd_nm": "보상"}

    # Mock GraphRetrievalResult
    from src.graph.retriever import GraphRetrievalResult, GraphFact

    mock_fact_no_ev = GraphFact(
        subject="테스트수술",
        relation="HAS_GRADE",
        object="신1-5종 4종",
        status="confirmed",
        confidence=1.0,
        evidence=[] # No evidence
    )

    mock_fact_with_ev = GraphFact(
        subject="테스트수술",
        relation="POLICY_COVERS_PROCEDURE",
        object="기관지 식도루 폐쇄술",
        status="confirmed",
        confidence=1.0,
        evidence=[MagicMock(evidence_id="ev_001", chunk_id="chunk_001", doc_short="약관")]
    )

    mock_graph_result = MagicMock(spec=GraphRetrievalResult)
    mock_graph_result.facts = [mock_fact_no_ev, mock_fact_with_ev]
    mock_graph_result.review_paths = []

    mock_rag = MagicMock()
    mock_rag.graph_enabled = True
    mock_rag.graph_retriever = MagicMock()
    mock_rag.graph_retriever.retrieve.return_value = mock_graph_result

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(
            rag_pipeline=mock_rag,
            items=items,
            context=context,
            use_fake_planner=True
        )

        # applied_basis에 evidence가 없는 'HAS_GRADE' confirmed fact의 정보가 들어갔는지 검사
        # source 명칭 등을 통해 확인 가능
        graph_bases = [b for b in result.applied_basis if "GraphDB" in b["source"]]
        # HAS_GRADE(evidence 없음)는 배제되어야 하므로, GraphDB 관련 근거 중 "HAS_GRADE"가 없어야 함
        assert not any("HAS_GRADE" in b["content"] for b in graph_bases)
        # POLICY_COVERS_PROCEDURE(evidence 있음)는 포함되어야 함
        assert any("POLICY_COVERS_PROCEDURE" in b["content"] for b in graph_bases)


def test_pipeline_candidate_pays_by_ratio_without_confirmed_forces_review():
    """candidate PAYS_BY_RATIO 정보만 있고 confirmed 정보가 없으면 review_required=True가 강제되는지 검증한다."""
    items = [ClaimItemInput(line_id="item_1", input_name="테스트수술", claimed_amount="100000")]
    context = ClaimCaseContext()

    mock_match = {"std_cd": "SC0001", "std_cd_nm": "테스트수술", "pay_opn_cd_nm": "보상"}

    # Mock GraphRetrievalResult with candidate PAYS_BY_RATIO only
    from src.graph.retriever import GraphRetrievalResult, GraphFact

    mock_fact_candidate = GraphFact(
        subject="테스트수술",
        relation="PAYS_BY_RATIO",
        object="30%",
        status="candidate",
        confidence=0.5,
        evidence=[]
    )

    mock_graph_result = MagicMock(spec=GraphRetrievalResult)
    mock_graph_result.facts = [mock_fact_candidate]
    mock_graph_result.review_paths = []

    mock_rag = MagicMock()
    mock_rag.graph_enabled = True
    mock_rag.graph_retriever = MagicMock()
    mock_rag.graph_retriever.retrieve.return_value = mock_graph_result

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(
            rag_pipeline=mock_rag,
            items=items,
            context=context,
            use_fake_planner=True
        )

        assert result.requires_review
        assert any("candidate PAYS_BY_RATIO" in reason for reason in result.review_reasons)
        assert result.notes == "추가 심사 검토가 필요합니다."
