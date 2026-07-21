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


def test_cross_doc_compare_keeps_balanced_search() -> None:
    plan = classify_search_intent("심평원과 SOL 건강보험 기준을 문서별로 비교해줘")

    assert plan.intent == "cross_doc_compare"
    assert plan.dense_weight == plan.bm25_weight
