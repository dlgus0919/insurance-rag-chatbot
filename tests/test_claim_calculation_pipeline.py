"""보험금 계산 파이프라인 통합 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from decimal import Decimal
import pytest

from src.claim_calculation.models import ClaimItemInput, ClaimCaseContext, CalculationResult
from src.claim_calculation.pipeline import run_claim_calculation


def test_pipeline_calculation_success_dousu():
    """도수치료 청구 시나리오에서 지급예상액이 올바르게 계산되고 파이프라인이 정상 동작하는지 검증한다."""
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
        # 150000원 청구 시 30%인 45,000원이 max(30000, 45000)으로 공제되어 105,000원이어야 함.
        assert result.payable_amount == "105000"
        assert result.deductible == "45000"
        assert not result.requires_review
        assert len(result.applied_basis) > 0
        assert "비급여 표준모델" in result.applied_basis[0]["source"]


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


def test_pipeline_over_claimed_warning():
    """지급예상액이 청구액보다 클 때 review 플래그가 활성화되는지 검증한다."""
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

    # Planner가 오작동하여 청구액보다 많은 금액을 주는 코드를 작성했다고 가정
    fake_intent = """
claimed_amount = Decimal('50000')
deductible = Decimal('0')
payable_amount = Decimal('100000')  # 50,000원 초과 청구액 발생
"""

    mock_plan = MagicMock()
    mock_plan.decision = "calculable"
    mock_plan.formula_intent = fake_intent
    mock_plan.uncertainties = []

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]), \
         patch("src.claim_calculation.planner.FakePlanner.plan", return_value=mock_plan):
        result = run_claim_calculation(
            rag_pipeline=None,
            items=items,
            context=context,
            use_fake_planner=True
        )

        assert result.payable_amount == "100000"
        assert result.requires_review
        assert any("초과합니다" in reason for reason in result.review_reasons)


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
            assert result.payable_amount == "105000"
            assert result.deductible == "45000"
            assert not result.requires_review


def test_pipeline_multiple_candidates_populate():
    """청구 항목의 표준코드 매칭 후보가 여러 개일 때, CalculationResult의 candidates 필드가 정상적으로 포퓰레이트되는지 검증한다."""
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
        assert len(result.candidates) == 2
        assert result.candidates[0]["code"] == "SC0001"
        assert result.candidates[1]["code"] == "MX122"


def test_fake_planner_amount_formatting_variations():
    """FakePlanner가 150000, 150,000, 150,000원 등 포맷팅된 금액을 예외 없이 파싱하여 계획을 세우는지 검증한다."""
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
        assert "Decimal('150000')" in plan.formula_intent
