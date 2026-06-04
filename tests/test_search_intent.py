from src.rag.search_intent import classify_search_intent


def test_exact_code_lookup_prioritizes_bm25_and_skips_dense() -> None:
    plan = classify_search_intent("N39.3 코드 보상돼?")

    assert plan.intent == "exact_code_lookup"
    assert plan.skip_dense is True
    assert plan.bm25_weight > plan.dense_weight
    assert plan.exact_terms == ["N39.3"]


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
