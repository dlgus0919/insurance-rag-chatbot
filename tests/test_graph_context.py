"""GraphDB context rendering tests."""

from __future__ import annotations

from src.graph.context import build_graph_context
from src.graph.query_planner import GraphQueryPlan
from src.graph.retriever import GraphFact, GraphRetrievalResult


def test_graph_context_preserves_conflicting_values() -> None:
    """같은 graph relation에 복수 값이 있으면 통합 금지 지침과 값 목록을 프롬프트에 포함한다."""

    result = GraphRetrievalResult(
        plan=GraphQueryPlan(intents=["surgery_grade_lookup"], procedure_name="테스트수술"),
        facts=[
            GraphFact(
                subject="테스트수술",
                relation="HAS_GRADE",
                object="신1-5종 4종",
                confidence=1.0,
                status="confirmed",
            ),
            GraphFact(
                subject="테스트수술",
                relation="HAS_GRADE",
                object="1-5종 3종",
                confidence=1.0,
                status="confirmed",
            ),
        ],
    )

    context = build_graph_context(result)

    assert "하나의 값으로 통합하지 말고" in context
    assert "GraphDB 복수 값/상충 후보" in context
    assert "테스트수술 --(HAS_GRADE)-->" in context
    assert "신1-5종 4종" in context
    assert "1-5종 3종" in context


def test_graph_context_category_table_keeps_multiple_fee_codes() -> None:
    """카테고리/등급 요약 표에서도 복수 수가코드를 덮어쓰지 않고 모두 유지한다."""

    result = GraphRetrievalResult(
        plan=GraphQueryPlan(
            intents=["category_grade_listing", "hira_code_lookup"],
            category="소화기계",
            grade_system="신1-5종",
            grade_value="5",
        ),
        facts=[
            GraphFact(
                subject="췌장 이식수술",
                relation="HAS_GRADE",
                object="신1-5종 5종",
                confidence=1.0,
                status="confirmed",
            ),
            GraphFact(
                subject="췌장 이식수술",
                relation="HAS_MEDICAL_FEE_CODE",
                object="Q8061 (췌이식술-부분)",
                confidence=1.0,
                status="confirmed",
            ),
            GraphFact(
                subject="췌장 이식수술",
                relation="HAS_MEDICAL_FEE_CODE",
                object="Q8062 (췌이식술-췌장 및 십이지장)",
                confidence=1.0,
                status="confirmed",
            ),
            GraphFact(
                subject="췌장 이식수술",
                relation="PAYS_BY_RATIO",
                object="100%",
                confidence=0.8,
                status="candidate",
            ),
        ],
    )

    context = build_graph_context(result)

    assert "| 췌장 이식수술 | 신1-5종 5종 |" in context
    assert "Q8061 (췌이식술-부분)" in context
    assert "Q8062 (췌이식술-췌장 및 십이지장)" in context
    assert "Q8061 (췌이식술-부분)<br>[CONFIRMED] Q8062" in context
