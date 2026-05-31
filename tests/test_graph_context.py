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
    assert "<br>" not in context
    assert "Q8061 (췌이식술-부분) / Q8062 (췌이식술-췌장 및 십이지장)" in context
    assert "[CANDIDATE] 100%" not in context
    assert "확정 답변 산출에서 제외한 GraphDB 항목" in context
    assert "췌장 이식수술 --(PAYS_BY_RATIO)--> candidate" in context


def test_graph_context_redacts_candidate_object_values() -> None:
    """후보 지급비율 값은 일반 컨텍스트에서도 확정 답변 재료로 노출하지 않는다."""

    result = GraphRetrievalResult(
        plan=GraphQueryPlan(intents=["policy_appendix_payment_lookup"]),
        facts=[
            GraphFact(
                subject="췌장 이식수술",
                relation="PAYS_BY_RATIO",
                object="100%",
                confidence=0.8,
                status="candidate",
                properties={"payment_ratio": "100%"},
            ),
        ],
    )

    context = build_graph_context(result)

    assert "100%" not in context
    assert "검토 후보(확정 대상 아님)" in context


def test_graph_context_includes_unconfirmed_term_correction_candidates() -> None:
    result = GraphRetrievalResult(
        plan=GraphQueryPlan(
            intents=["ordinary_rag"],
            term_correction_candidates=[
                {
                    "raw": "엠알아이",
                    "normalized": "MRI",
                    "reason": "사용자 입력 표현 확인 필요",
                }
            ],
            clarification_questions=["'엠알아이' 표현이 'MRI'을 의미하는지 확인해 주세요."],
        )
    )

    context = build_graph_context(result)

    assert "입력 용어 보정 후보 (미확정)" in context
    assert "엠알아이 -> MRI" in context
    assert "확인 전에는 보상 판단의 전제로 삼지 마십시오" in context
