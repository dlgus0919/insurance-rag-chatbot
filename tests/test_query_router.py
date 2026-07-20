from src.rag.query_router import resolve_query_route


def test_general_explanation_stays_on_general_strategy() -> None:
    route = resolve_query_route("보험계약의 고지의무를 쉽게 설명해줘")

    assert route.route == "general"
    assert route.intent == "general_explanation"


def test_quick_code_question_reuses_quickcode_strategy() -> None:
    route = resolve_query_route("식도조루술 수가 코드와 점수를 알려줘")

    assert route.route == "quickcode"
    assert route.route_reason == "procedure_code_intent"
    assert route.filters["include_summary"] is True
    assert route.filters["include_coverage"] is False
    assert route.filters["_auto_routed"] is True


def test_quick_code_with_coverage_reuses_combined_quickcode_strategy() -> None:
    route = resolve_query_route("식도조루술 수가 코드와 실손 보상 여부를 알려줘")

    assert route.route == "quickcode"
    assert route.filters["include_summary"] is True
    assert route.filters["include_coverage"] is True


def test_simple_coverage_question_keeps_general_graph_strategy() -> None:
    route = resolve_query_route("도수치료 보상돼?")

    assert route.route == "general"


def test_pure_policy_attribute_uses_general_direct_retrieval_strategy() -> None:
    route = resolve_query_route("검사X의 연간 보상한도는?")

    assert route.route == "general"
    assert route.intent == "policy_attribute_lookup"
    assert route.route_reason == "policy_attribute_direct_lookup"


def test_policy_attribute_coverage_question_keeps_coverage_route() -> None:
    route = resolve_query_route("5세대 MRI 연간 보장되나요?")

    assert route.route == "general"
    assert route.intent != "policy_attribute_lookup"


def test_coverage_question_reuses_formal_strategy_without_forcing_product_scope() -> None:
    route = resolve_query_route("N39.3 진단코드는 4세대 실손 질병급여에서 보상 가능한가요?")

    assert route.route == "formal"
    assert route.formal_mode == "coverage_judgment"
    assert route.route_reason == "structured_coverage_cue"
    assert route.filters["search_type"] == "보상가능 여부 판정"
    assert route.filters["_auto_routed"] is True
    assert "product_category" not in route.filters
    assert route.coverage_topics == ["질병급여"]


def test_clause_question_reuses_formal_clause_strategy() -> None:
    route = resolve_query_route("실손보험 약관 제12조와 별표 내용을 찾아줘")

    assert route.route == "formal"
    assert route.formal_mode == "clause_lookup"
    assert route.route_reason == "clause_lookup_intent"
    assert route.article_number == "12"
    assert route.include_appendix is True
    assert route.filters["search_type"] == "약관 조문 검색"


def test_clause_question_does_not_force_a_product_document_scope() -> None:
    route = resolve_query_route(
        "자동차사고 부상치료지원금 담보를 청구하려고 합니다. 필요한 서류를 알려주세요."
    )

    assert route.route == "formal"
    assert route.formal_mode == "clause_lookup"
    assert "product_category" not in route.filters


def test_general_surgery_grade_question_keeps_general_graph_strategy() -> None:
    route = resolve_query_route("기관지 식도루 폐쇄술의 신1-5종 수술 종수는?")

    assert route.route == "general"


def test_explicit_scope_filter_is_preserved() -> None:
    route = resolve_query_route(
        "백내장 수술 코드 알려줘",
        {"doc_filter": ["심평원"]},
    )

    assert route.route == "quickcode"
    assert route.filters["doc_filter"] == ["심평원"]
