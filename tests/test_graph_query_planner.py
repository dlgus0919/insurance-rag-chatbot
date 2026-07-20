from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.graph.query_planner import GraphQueryPlanner, GraphQueryPlan
from src.ontology.registry import OntologyRegistry


def _forensic_source_grounded_registry(tmp_path: Path) -> OntologyRegistry:
    manifest = {
        "schema_version": "1.0",
        "version": "forensic-fixture",
        "concepts": [
            {
                "concept_id": "test.forensic_hair_loss",
                "canonical_name": "탈모",
                "node_type": "ClaimCondition",
                "aliases": ["탈모"],
                "planner": {
                    "coverage_topics": ["탈모"],
                    "clarification_questions": [
                        "노화현상으로 인한 탈모인지, 질병성 탈모인지 확인이 필요합니다."
                    ],
                    "required_evidence": ["진단명 또는 진단코드", "의사소견"],
                },
            }
        ],
    }
    manifest_path = tmp_path / "forensic_source_grounded_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return OntologyRegistry(manifest_path, enforce_integrity=False)


@pytest.mark.parametrize(
    ("query", "procedure", "grade_system"),
    [
        ("결장폴립절제술은 1~5종에서 몇종으로 줘?", "결장폴립절제술", "1-5종"),
        ("결장경하 폴립절제술 종수를 알려줘", "결장경하 폴립절제술", None),
    ],
)
def test_surgery_grade_query_normalizes_compact_korean_forms(
    query: str,
    procedure: str,
    grade_system: str | None,
) -> None:
    plan = GraphQueryPlanner().plan(query)

    assert plan.procedure_name == procedure
    assert plan.grade_system == grade_system
    assert plan.grade_value is None
    assert "surgery_grade_lookup" in plan.intents


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


def test_query_planner_does_not_treat_surgery_suffix_as_drunk_injury() -> None:
    plan = GraphQueryPlanner().plan("충수절제술의 1-5종 수술종수는?")

    assert plan.conditions.count("음주 후 상해") == 0
    assert plan.normalized_terms.get("술") is None


@pytest.mark.parametrize("query", ["술먹고 다쳤습니다.", "술마시고 넘어졌어요."])
def test_query_planner_matches_attached_standalone_drinking_expression(query: str) -> None:
    plan = GraphQueryPlanner().plan(query)

    assert "음주 후 상해" in plan.conditions


def test_query_planner_hair_loss_adds_source_grounded_cause_questions(tmp_path: Path) -> None:
    plan = GraphQueryPlanner(
        ontology_registry=_forensic_source_grounded_registry(tmp_path)
    ).plan("탈모 보상 가능?")

    assert "탈모" in plan.coverage_topics
    assert any("노화현상" in question and "질병성 탈모" in question for question in plan.clarification_questions)
    assert "진단명 또는 진단코드" in plan.required_evidence
    assert "의사소견" in plan.required_evidence


def test_query_planner_uses_selected_generation_for_confirmed_policy_attribute_lookup() -> None:
    plan = GraphQueryPlanner().plan(
        "자기공명영상진단(MRI/MRA)의 연간 보상한도는?",
        policy_generation="5th",
    )

    assert plan.policy_generation == "5th"
    assert plan.term_correction_candidates == []
    assert "실손 세대" not in plan.ambiguous_terms
    assert "방문 구분" not in plan.ambiguous_terms
    assert "증빙 서류" not in plan.ambiguous_terms


def test_query_planner_keeps_visit_and_evidence_for_policy_attribute_coverage_decision() -> None:
    plan = GraphQueryPlanner().plan("5세대 MRI 연간 보상 가능한가요?", policy_generation="5th")

    assert plan.policy_generation == "5th"
    assert "실손 세대" not in plan.ambiguous_terms
    assert "방문 구분" in plan.ambiguous_terms
    assert "증빙 서류" in plan.ambiguous_terms


@pytest.mark.parametrize(
    "query",
    [
        "5세대 MRI 연간 보험금 계산을 해주세요.",
        "5세대 MRI 연간 청구 가능 여부를 알려주세요.",
        "5세대 MRI 연간 보장되나요?",
        "5세대 MRI 연간 받을 수 있나요?",
        "5세대 MRI 연간 보상 가능 여부가 궁금합니다.",
        "5세대 MRI 연간 지급 가능한가요?",
        "5세대 MRI 연간 보장 대상인가요?",
    ],
)
def test_query_planner_keeps_visit_and_evidence_for_policy_attribute_claim_or_calculation(
    query: str,
) -> None:
    plan = GraphQueryPlanner().plan(query, policy_generation="5th")

    assert plan.policy_generation == "5th"
    assert "방문 구분" in plan.ambiguous_terms
    assert "증빙 서류" in plan.ambiguous_terms


def test_query_planner_keeps_standalone_candidate_for_unconfirmed_short_term() -> None:
    plan = GraphQueryPlanner().plan("자기공명의 연간 보상한도는?", policy_generation="5th")

    assert plan.policy_generation == "5th"
    assert any(candidate["raw"] == "자기공명" for candidate in plan.term_correction_candidates)
    assert "용어 보정 후보" in plan.ambiguous_terms


def test_query_planner_uses_ui_generation_over_a_single_explicit_generation() -> None:
    plan = GraphQueryPlanner().plan("4세대 MRI 연간 보상한도는?", policy_generation="5th")

    assert plan.policy_generation == "5th"
    assert not plan.policy_generation_comparison


def test_query_planner_keeps_an_explicit_generation_comparison_unrestricted() -> None:
    plan = GraphQueryPlanner().plan(
        "4세대와 5세대 MRI/MRA 연간 보상한도 차이는?",
        policy_generation="5th",
    )

    assert plan.policy_generation is None
    assert plan.policy_generation_comparison
    assert "실손 세대" not in plan.ambiguous_terms
    assert "방문 구분" not in plan.ambiguous_terms
    assert "증빙 서류" not in plan.ambiguous_terms


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
