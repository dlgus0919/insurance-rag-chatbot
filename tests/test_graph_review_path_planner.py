from __future__ import annotations

from src.graph.query_planner import GraphQueryPlanner


def test_query_planner_extracts_review_path_signals() -> None:
    planner = GraphQueryPlanner()
    plan = planner.plan("당뇨 진단을 받고 나서 눈이 안 좋아져 망막 레이저 수술을 받았는데, 합병증 특약 보상이 되나요?")

    assert plan.complication_asserted is True
    assert "complication_policy_lookup" in plan.intents
    assert "session_claim_path_review" in plan.intents
    assert "특약" in plan.coverage_topics


def test_query_planner_extracts_diagnosis_context() -> None:
    planner = GraphQueryPlanner()
    plan = planner.plan("N39.3 진단으로 질병급여 실손의료비 청구가 가능한가요?")

    assert plan.diagnosis_codes == ["N39.3"]
    assert "diagnosis_policy_lookup" in plan.intents
    assert "실손" in plan.coverage_topics


def test_query_planner_does_not_treat_inflammation_alone_as_complication() -> None:
    planner = GraphQueryPlanner()
    plan = planner.plan("눈 염증으로 실손 청구가 가능한가요?")

    assert plan.complication_asserted is False
    assert "complication_policy_lookup" not in plan.intents


def test_query_planner_treats_post_surgery_inflammation_as_complication() -> None:
    planner = GraphQueryPlanner()
    plan = planner.plan("미용 목적 수술 후 염증이 생겼는데 합병증 치료비를 받을 수 있나요?")

    assert plan.complication_asserted is True
    assert "complication_policy_lookup" in plan.intents



def test_query_planner_normalizes_practical_claim_terms_and_requests_context() -> None:
    planner = GraphQueryPlanner()
    plan = planner.plan('진료비 세부내역서 없이 영수증만 있는 도수치료 청구를 자동 계산해도 되나요?')

    assert '도수치료' in plan.coverage_topics
    assert '증빙 부족' in plan.conditions
    assert plan.normalized_terms['세부내역서 없이'] == '증빙 부족'
    assert plan.normalized_terms['영수증만'] == '증빙 부족'
    assert '실손 세대' in plan.ambiguous_terms
    assert '방문 구분' in plan.ambiguous_terms
    assert any('실손 세대' in question for question in plan.clarification_questions)
    assert any('입원/통원' in question for question in plan.clarification_questions)


def test_query_planner_treats_health_check_mri_as_preventive_context() -> None:
    planner = GraphQueryPlanner()
    plan = planner.plan('건강검진 중 이상 소견 없이 받은 MRI 비용도 실손으로 보상되나요?')

    assert '건강검진' in plan.coverage_topics
    assert 'MRI' in plan.coverage_topics
    assert '예방 목적' in plan.conditions
    assert '치료 목적' in plan.ambiguous_terms
    assert any('치료 목적인지' in question for question in plan.clarification_questions)


def test_query_planner_keeps_third_party_insurance_overlap_as_review_condition() -> None:
    planner = GraphQueryPlanner()
    plan = planner.plan('자동차보험으로 이미 보상받은 치료비를 실손에서도 청구할 수 있나요?')

    assert '자동차보험' in plan.coverage_topics
    assert '실손' in plan.coverage_topics
    assert '타 보험 보상' in plan.conditions
    assert plan.normalized_terms['이미 보상'] == '타 보험 보상'
    assert 'session_claim_path_review' in plan.intents


def test_query_planner_adds_unconfirmed_term_correction_candidate() -> None:
    planner = GraphQueryPlanner()
    plan = planner.plan('엠알아이 비용도 실비로 청구 가능한가요?')

    assert plan.normalized_terms['실비'] == '실손'
    assert 'MRI' not in plan.coverage_topics
    assert plan.term_correction_candidates[0]['raw'] == '엠알아이'
    assert plan.term_correction_candidates[0]['normalized'] == 'MRI'
    assert '용어 보정 후보' in plan.ambiguous_terms
    assert any('엠알아이' in question and 'MRI' in question for question in plan.clarification_questions)
    assert 'ordinary_rag' in plan.intents
