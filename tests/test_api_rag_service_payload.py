from src.api.rag_service import graph_result_to_payload
from src.graph.query_planner import GraphQueryPlan
from src.graph.retriever import GraphPathStep, GraphRetrievalResult, GraphReviewPath


def test_graph_result_to_payload_adds_review_display_labels() -> None:
    result = GraphRetrievalResult(
        plan=GraphQueryPlan(intents=["complication_policy_lookup"]),
        review_paths=[
            GraphReviewPath(
                path_id="complication::test",
                path_type="complication_review",
                status="review_required",
                summary="합병증 관련 조항 검토",
                steps=[
                    GraphPathStep(
                        source="session",
                        subject="질문/입력",
                        relation="ASSERTS",
                        object="합병증",
                        status="asserted",
                    )
                ],
            )
        ],
    )

    payload = graph_result_to_payload(result)

    assert payload is not None
    path = payload["graph_review_paths"][0]
    assert path["path_type_label"] == "합병증/후유증 검토"
    assert path["status_label"] == "검토 필요"



def test_graph_result_to_payload_includes_clarification_and_normalized_terms() -> None:
    result = GraphRetrievalResult(
        plan=GraphQueryPlan(
            intents=['session_claim_path_review'],
            coverage_topics=['도수치료'],
            conditions=['증빙 부족'],
            normalized_terms={'영수증만': '증빙 부족'},
            term_correction_candidates=[{'raw': '엠알아이', 'normalized': 'MRI', 'confidence': 0.72}],
            ambiguous_terms=['실손 세대'],
            clarification_questions=['어느 실손 세대 기준인지 확인해 주세요.'],
        )
    )

    payload = graph_result_to_payload(result)

    assert payload is not None
    assert payload['plan']['normalized_terms'] == {'영수증만': '증빙 부족'}
    assert payload['plan']['term_correction_candidates'][0]['raw'] == '엠알아이'
    assert payload['plan']['ambiguous_terms'] == ['실손 세대']
    assert payload['plan']['clarification_questions'] == ['어느 실손 세대 기준인지 확인해 주세요.']
