from __future__ import annotations

import pytest

from src.graph.query_planner import GraphQueryPlanner, GraphQueryPlan


def test_query_planner_hard_query_1() -> None:
    planner = GraphQueryPlanner()
    query = (
        "기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, "
        "이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘. "
        "그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘."
    )
    plan = planner.plan(query)

    assert plan.procedure_name in ["기관지 식도루 폐쇄술", "기관지식도루폐쇄술"]
    assert plan.grade_system == "신1-5종"
    assert "surgery_grade_lookup" in plan.intents
    assert "same_grade_surgery_list" in plan.intents
    assert "policy_appendix_payment_lookup" in plan.intents
    assert plan.requested_peer_count == 3
    assert plan.policy_product in ["SOL", "처음건강보험", "자사_SOL건강"]
    assert plan.appendix == "별표7"


def test_query_planner_hard_query_2() -> None:
    planner = GraphQueryPlanner()
    query = (
        "신1-5종 수술분류표에서 5종(가장 중한 등급)에 해당하는 수술을 "
        "소화기계 카테고리에서 모두 나열해줘. "
        "각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘."
    )
    plan = planner.plan(query)

    assert plan.grade_system == "신1-5종"
    assert plan.grade_value == "5"
    assert plan.category == "소화기계"
    assert plan.procedure_name is None
    assert "category_grade_listing" in plan.intents
    assert "policy_appendix_payment_lookup" in plan.intents
    assert "hira_code_lookup" in plan.intents


def test_query_planner_ordinary_rag() -> None:
    planner = GraphQueryPlanner()
    query = "일반적인 실손보험 청구 서류가 어떻게 되나요?"
    plan = planner.plan(query)

    assert "ordinary_rag" in plan.intents
    assert plan.procedure_name is None
    assert plan.grade_system is None


def test_query_planner_comparison_no_extraction() -> None:
    planner = GraphQueryPlanner()
    query = "기관지 식도루 폐쇄술과 간장 이식수술의 차이점과 각각 해당하는 수술종류를 알려주세요."
    plan = planner.plan(query)
    # "차이점과 각각 해당하는 수술종류"가 수술명으로 오추출되지 않음을 보장
    assert plan.procedure_name != "차이점과 각각 해당하는 수술종류"
    # 여기서는 "기관지 식도루 폐쇄술"이 우선 추출되어야 함
    assert plan.procedure_name == "기관지 식도루 폐쇄술"


def test_query_planner_appendix_numbers() -> None:
    planner = GraphQueryPlanner()
    # 1. 18번 항목, 19번 항목이 명시된 경우
    query_explicit = "SOL 건강보험 별표7의 18번 항목과 19번 항목의 차이점과 각각 해당하는 수술종류를 알려주세요."
    plan_explicit = planner.plan(query_explicit)
    assert plan_explicit.appendix_numbers == ["18", "19"]

    # 2. 신1-5종 및 별표7, 3가지 등 오인 가능한 숫자가 섞인 경우
    query_complex = (
        "기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, "
        "이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘. "
        "그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘."
    )
    plan_complex = planner.plan(query_complex)
    assert plan_complex.appendix_numbers == []
