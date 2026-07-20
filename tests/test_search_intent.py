from src.rag.search_intent import classify_search_intent


def test_exact_code_lookup_prioritizes_bm25_but_preserves_dense_filter() -> None:
    plan = classify_search_intent("N39.3 코드 보상돼?")

    assert plan.intent == "exact_code_compound_lookup"
    assert plan.skip_dense is False
    assert plan.skip_general_dense is False
    assert plan.bm25_weight > plan.dense_weight
    assert plan.exact_terms == ["N39.3"]
    assert plan.has_exact_code is True
    assert plan.requires_coverage_judgment is True


def test_pure_exact_code_lookup_can_plan_general_dense_skip_only() -> None:
    plan = classify_search_intent("AA157 코드")

    assert plan.intent == "exact_code_lookup"
    assert plan.skip_dense is False
    assert plan.skip_general_dense is True
    assert plan.exact_terms == ["AA157"]


def test_numeric_standard_code_is_detected_with_code_context() -> None:
    plan = classify_search_intent("도수치료 표준코드 51040의 면책 여부")

    assert "51040" in plan.exact_terms
    assert plan.has_exact_code is True


def test_numeric_amount_is_not_detected_as_code() -> None:
    plan = classify_search_intent("도수치료 100000원 청구하면 얼마 보상돼?")

    assert plan.exact_terms == []
    assert plan.intent == "coverage_judgment"


def test_compound_code_clause_query_keeps_semantic_search() -> None:
    plan = classify_search_intent("N39.3 약관 근거와 보상 조건을 알려줘")

    assert plan.intent == "exact_code_compound_lookup"
    assert plan.skip_general_dense is False
    assert plan.requires_clause_lookup is True
    assert plan.requires_coverage_judgment is True


def test_clause_lookup_prioritizes_keyword_search() -> None:
    plan = classify_search_intent("실손보험 약관 제12조와 별표7 내용을 알려줘")

    assert plan.intent == "clause_or_appendix_lookup"
    assert plan.skip_dense is False
    assert plan.bm25_weight > plan.dense_weight


def test_ambiguous_coverage_query_prioritizes_chroma() -> None:
    plan = classify_search_intent("도수치료 받았는데 돈 나오나요?")

    assert plan.intent == "coverage_judgment"
    assert plan.dense_weight > plan.bm25_weight
    assert plan.top_k_dense > plan.top_k_bm25


def test_mri_transliteration_is_classified_as_ambiguous_medical_term() -> None:
    plan = classify_search_intent("엠알아이 찍었는데 실손 보장돼?")

    assert plan.intent == "ambiguous_medical_term"
    assert plan.dense_weight > plan.bm25_weight


def test_pure_policy_attribute_lookup_outranks_ambiguous_medical_term() -> None:
    plan = classify_search_intent("자기공명영상진단(MRI/MRA)의 연간 보상한도는?")

    assert plan.intent == "policy_attribute_lookup"
    assert plan.requires_clause_lookup is True
    assert plan.requires_coverage_judgment is False


def test_policy_attribute_coverage_question_keeps_coverage_judgment() -> None:
    plan = classify_search_intent("5세대 MRI의 연간 보상한도는 보장되나요?")

    assert plan.requires_coverage_judgment is True


def test_policy_attribute_noun_queries_stay_in_direct_lookup() -> None:
    for question in (
        "검사X 연간 보상한도는?",
        "검사X 횟수한도는?",
        "검사X 보장기간은?",
        "검사X 지급한도는?",
        "검사X 지급기간은?",
        "검사X 공제금액은?",
        "검사X 보상비율은?",
    ):
        plan = classify_search_intent(question)

        assert plan.intent == "policy_attribute_lookup"
        assert plan.requires_coverage_judgment is False


def test_policy_attribute_action_queries_keep_coverage_judgment() -> None:
    for question in (
        "검사X 연간 보상한도 계산해줘",
        "검사X 연간 보상한도 청구하면?",
        "검사X 연간 보상한도 지급받을 수 있나요?",
        "검사X 연간 보상한도 보험금 판단이 필요해",
    ):
        plan = classify_search_intent(question)

        assert plan.intent != "policy_attribute_lookup"
        assert plan.requires_coverage_judgment is True


def test_policy_attribute_decision_inflections_keep_coverage_judgment() -> None:
    for question in (
        "검사X 보상한도 지급 여부는?",
        "검사X 보상한도 지급되는지 알려줘",
        "검사X 보상한도 보험금은?",
        "검사X 보상한도 보험금 지급 판단이 필요해",
        "5세대 MRI 연간 보장되나요?",
        "5세대 MRI 보상한도 지급 여부는?",
    ):
        plan = classify_search_intent(question)

        assert plan.intent != "policy_attribute_lookup"
        assert plan.requires_coverage_judgment is True


def test_cross_doc_compare_keeps_balanced_search() -> None:
    plan = classify_search_intent("심평원과 SOL 건강보험 기준을 문서별로 비교해줘")

    assert plan.intent == "cross_doc_compare"
    assert plan.dense_weight == plan.bm25_weight
