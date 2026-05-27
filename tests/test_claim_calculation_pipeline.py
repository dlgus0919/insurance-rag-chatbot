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
        assert result.policy_generation == "4th"
        assert result.line_results[0]["payable_amount"] == "105000"
        assert not result.requires_review
        assert len(result.applied_basis) > 0
        assert "비급여 표준모델" in result.applied_basis[0]["source"]


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


def test_fifth_generation_three_nonpay_uses_nonsevere_rate():
    """5세대 도수치료 등 3대비급여는 비중증 비급여 공제 기준을 적용한다."""
    items = [ClaimItemInput(line_id="line_dosu", input_name="도수치료", claimed_amount="100000", user_category_hint="3대비급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == "50000"
    assert result.payable_amount == "50000"
    assert result.requires_review
    assert "5세대 3대비급여" in result.line_results[0]["rule_summary"]


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
def test_llm_generated_formula_variants_execute_in_sandbox(
    monkeypatch,
    case_name: str,
    items: list[ClaimItemInput],
    context: ClaimCaseContext,
    formula: str,
    expected_claimed: str,
    expected_deductible: str,
    expected_payable: str,
):
    """LLM이 생성한 서로 다른 계산 코드 형태도 샌드박스에서 실행되어 결과값으로 반영된다."""

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
    assert result.executed_code == formula
    assert "Decimal" in result.executed_code


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
        assert any("급여/비급여" in reason or "불명확" in reason for reason in result.review_reasons)


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


# =====================================================================
# Phase 1 추가 테스트: 의료기관 등급별 공제, 건당 한도, 처방약
# =====================================================================

def test_4th_outpatient_clinic_min_deductible():
    """4세대 의원 급여 통원: 최소공제 10,000원 적용."""
    items = [ClaimItemInput(line_id="fc1", input_name="진찰료", claimed_amount="30000", user_category_hint="급여")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th", facility_grade="clinic")
    mock_match = {"std_cd": "SC001", "std_cd_nm": "진찰료", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert result.deductible == "10000"
    assert result.payable_amount == "20000"


def test_4th_outpatient_hospital_min_deductible():
    """4세대 병원 급여 통원: 최소공제 15,000원 적용."""
    items = [ClaimItemInput(line_id="fc2", input_name="진찰료", claimed_amount="30000", user_category_hint="급여")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th", facility_grade="hospital")
    mock_match = {"std_cd": "SC001", "std_cd_nm": "진찰료", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert result.deductible == "15000"
    assert result.payable_amount == "15000"


def test_4th_outpatient_general_hospital_min_deductible():
    """4세대 종합병원 급여 통원: 최소공제 20,000원 적용."""
    items = [ClaimItemInput(line_id="fc3", input_name="진찰료", claimed_amount="30000", user_category_hint="급여")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th", facility_grade="general_hospital")
    mock_match = {"std_cd": "SC001", "std_cd_nm": "진찰료", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert result.deductible == "20000"
    assert result.payable_amount == "10000"


def test_5th_outpatient_clinic_benefit():
    """5세대 의원 급여 통원: 최소공제 10,000원 적용."""
    items = [ClaimItemInput(line_id="fc4", input_name="진찰료", claimed_amount="30000", user_category_hint="급여")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="5th", facility_grade="clinic")
    mock_match = {"std_cd": "SC001", "std_cd_nm": "진찰료", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert result.deductible == "10000"
    assert result.payable_amount == "20000"


def test_5th_outpatient_nonserious_hospital():
    """5세대 병원 비중증비급여 통원: 50% 공제 및 최소공제 50,000원."""
    items = [ClaimItemInput(line_id="fc5", input_name="도수치료", claimed_amount="200000", user_category_hint="비중증비급여")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="5th", facility_grade="hospital")
    mock_match = {"std_cd": "MX122", "std_cd_nm": "도수치료", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert result.deductible == "100000"
    assert result.payable_amount == "100000"


def test_per_visit_limit_4th_outpatient():
    """4세대 통원 건당 250,000원 한도 적용: 400,000원 청구 시 공제 후 남는 지급분이 한도를 초과."""
    items = [ClaimItemInput(line_id="pvl1", input_name="진찰료", claimed_amount="400000", user_category_hint="급여")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th", facility_grade="clinic")
    mock_match = {"std_cd": "SC001", "std_cd_nm": "진찰료", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    # 20% of 400000 = 80000 deductible, payable = 320000 > 250000 limit
    assert result.payable_amount == "250000"
    assert any("건당 한도" in r for r in result.review_reasons)


def test_per_visit_limit_5th_outpatient():
    """5세대 통원 건당 200,000원 한도 적용."""
    items = [ClaimItemInput(line_id="pvl2", input_name="진찰료", claimed_amount="400000", user_category_hint="급여")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="5th", facility_grade="clinic")
    mock_match = {"std_cd": "SC001", "std_cd_nm": "진찰료", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    # 20% of 400000 = 80000 deductible, payable = 320000 > 200000 limit
    assert result.payable_amount == "200000"
    assert any("건당 한도" in r for r in result.review_reasons)


def test_prescription_4th_deductible():
    """4세대 처방약: 8,000원 공제, 건당 50,000원 한도."""
    items = [ClaimItemInput(line_id="rx1", input_name="처방약", claimed_amount="30000", user_category_hint="처방약")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th")
    mock_match = {"std_cd": "", "std_cd_nm": "처방약", "pay_opn_cd_nm": ""}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert result.deductible == "8000"
    assert result.payable_amount == "22000"


def test_prescription_5th_deductible():
    """5세대 처방약: 8,000원 공제."""
    items = [ClaimItemInput(line_id="rx2", input_name="처방약", claimed_amount="30000", user_category_hint="처방약")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="5th")
    mock_match = {"std_cd": "", "std_cd_nm": "처방약", "pay_opn_cd_nm": ""}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert result.deductible == "8000"
    assert result.payable_amount == "22000"


def test_prescription_per_visit_limit():
    """처방약 건당 한도 50,000원 초과 시 한도 적용."""
    items = [ClaimItemInput(line_id="rx3", input_name="처방약", claimed_amount="80000", user_category_hint="처방약")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th")
    mock_match = {"std_cd": "", "std_cd_nm": "처방약", "pay_opn_cd_nm": ""}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    # 80000 - 8000 = 72000 > 50000, 한도 적용
    assert result.payable_amount == "50000"
    assert any("처방약 건당 한도" in r for r in result.review_reasons)


def test_prescription_auto_detect_keyword():
    """input_name에 '약제비' 키워드 → 자동 처방약 분류."""
    items = [ClaimItemInput(line_id="rx4", input_name="약제비", claimed_amount="20000")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th")
    mock_match = {"std_cd": "", "std_cd_nm": "약제비", "pay_opn_cd_nm": ""}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert result.deductible == "8000"
    assert result.payable_amount == "12000"
    # line_results에서 category가 처방약인지 확인
    assert result.line_results[0]["category"] == "처방약"


def test_prescription_is_prescription_flag():
    """is_prescription=True 플래그 → 처방약 분류 우선."""
    items = [ClaimItemInput(line_id="rx5", input_name="일반항목", claimed_amount="25000", is_prescription=True)]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th")
    mock_match = {"std_cd": "", "std_cd_nm": "일반항목", "pay_opn_cd_nm": ""}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert result.line_results[0]["category"] == "처방약"
    assert result.deductible == "8000"


def test_no_facility_grade_fallback():
    """의료기관 등급 미입력 시 의원(clinic) 기본 적용."""
    items = [ClaimItemInput(line_id="fb1", input_name="진찰료", claimed_amount="30000", user_category_hint="급여")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th", facility_grade="")
    mock_match = {"std_cd": "SC001", "std_cd_nm": "진찰료", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    # 의원 기본: 최소공제 10000, 20% of 30000 = 6000 < 10000
    assert result.deductible == "10000"


def test_hospitalization_ignores_facility_grade():
    """입원은 의료기관 등급별 최소공제 없음 (0원)."""
    items = [ClaimItemInput(line_id="hi1", input_name="수술비", claimed_amount="1000000", user_category_hint="급여")]
    context = ClaimCaseContext(visit_type="hospitalization", policy_generation="4th", facility_grade="tertiary_hospital")
    mock_match = {"std_cd": "SC001", "std_cd_nm": "수술비", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    # 20% of 1000000 = 200000, no min deductible for hospitalization
    assert result.deductible == "200000"
    assert result.payable_amount == "800000"


def test_applied_limits_populated():
    """결과에 applied_limits 정보 포함 확인."""
    items = [ClaimItemInput(line_id="al1", input_name="진찰료", claimed_amount="50000", user_category_hint="급여")]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th")
    mock_match = {"std_cd": "SC001", "std_cd_nm": "진찰료", "pay_opn_cd_nm": "보상"}
    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    assert "per_visit_limit" in result.applied_limits
    assert "remaining_note" in result.applied_limits


def test_mixed_prescription_and_treatment():
    """처방약 + 진료비 복합 항목 합산."""
    items = [
        ClaimItemInput(line_id="mx1", input_name="도수치료", claimed_amount="150000", user_category_hint="비급여"),
        ClaimItemInput(line_id="mx2", input_name="처방약", claimed_amount="30000", user_category_hint="처방약"),
    ]
    context = ClaimCaseContext(visit_type="outpatient", policy_generation="4th", facility_grade="clinic")
    mock_matches = [
        {"std_cd": "MX122", "std_cd_nm": "도수치료", "pay_opn_cd_nm": "보상"},
        {"std_cd": "", "std_cd_nm": "처방약", "pay_opn_cd_nm": ""},
    ]
    with patch("src.db.standard_codes.search_by_name", side_effect=[[mock_matches[0]], [mock_matches[1]]]):
        result = run_claim_calculation(rag_pipeline=None, items=items, context=context, use_fake_planner=True)
    # 도수치료: 30% of 150000 = 45000 deductible, payable = 105000
    # 처방약: 8000 deductible, payable = 22000
    assert len(result.line_results) == 2
    assert result.line_results[0]["category"] == "3대비급여"  # 도수치료 → 3대비급여 자동 분류
    assert result.line_results[1]["category"] == "처방약"
    total_payable = int(result.payable_amount)
    total_deductible = int(result.deductible)
    # 4세대 도수치료(3대비급여=비급여 동일 30%): 150000 * 0.3 = 45000 deductible, payable = 105000
    # 처방약: 8000 deductible, payable = 22000
    assert total_payable == 105000 + 22000  # 127000
    assert total_deductible == 45000 + 8000  # 53000
