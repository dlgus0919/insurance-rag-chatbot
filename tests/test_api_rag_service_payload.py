from src.api.rag_service import graph_result_to_payload
from src.graph.query_planner import GraphQueryPlan
from src.graph.retriever import GraphEvidence, GraphFact, GraphPathStep, GraphRetrievalResult, GraphReviewPath
from src.retrieval.chunk_lookup import ChunkLookupRef


def test_graph_result_to_payload_adds_review_display_labels() -> None:
    result = GraphRetrievalResult(
        plan=GraphQueryPlan(intents=["complication_policy_lookup"]),
        review_paths=[
            GraphReviewPath(
                path_id="complication::test",
                path_type="complication_review",
                status="review_required",
                summary="합병증 관련 조항 검토",
                exclusion_reasons=["미용 목적"],
                required_documents=["진단서"],
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
    assert path["exclusion_reasons"] == ["미용 목적"]
    assert path["required_documents"] == ["진단서"]
    assert payload["exclusion_reasons"] == ["미용 목적"]
    assert payload["required_documents"] == ["진단서"]


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
        ),
        source_chunk_refs=[
            ChunkLookupRef(
                requested_id="실무가이드_v2_manual_ch_000111",
                canonical_chunk_id="실무가이드:000111",
                source_chunk_id="실무가이드_ch_000111",
                doc_short="실무가이드",
                page_start=80,
                page_end=80,
            )
        ],
    )

    payload = graph_result_to_payload(result)

    assert payload is not None
    assert payload['plan']['normalized_terms'] == {'영수증만': '증빙 부족'}
    assert payload['plan']['term_correction_candidates'][0]['raw'] == '엠알아이'
    assert payload['plan']['ambiguous_terms'] == ['실손 세대']
    assert payload['plan']['clarification_questions'] == ['어느 실손 세대 기준인지 확인해 주세요.']
    assert payload["source_chunk_refs"][0]["requested_id"] == "실무가이드_v2_manual_ch_000111"
    assert payload["source_chunk_refs"][0]["canonical_chunk_id"] == "실무가이드:000111"
    assert payload["source_chunk_refs"][0]["source_chunk_id"] == "실무가이드_ch_000111"


def test_graph_result_to_payload_adds_four_section_summary_and_isolates_candidate_confidence() -> None:
    result = GraphRetrievalResult(
        plan=GraphQueryPlan(intents=["hira_code_lookup"]),
        facts=[
            GraphFact(
                subject="췌장 이식수술",
                relation="HAS_MEDICAL_FEE_CODE",
                object="Q8061",
                confidence=0.95,
                status="confirmed",
                evidence=[
                    GraphEvidence(
                        evidence_id="ev-1",
                        chunk_id="chunk-1",
                        doc_short="심평원",
                        page_start=638,
                    )
                ],
            )
        ],
        required_evidence=["수술확인서"],
        review_actions=["수가코드 원문 재확인"],
    )

    payload = graph_result_to_payload(result)

    assert payload is not None
    summary = payload["graph_summary"]
    assert summary["confirmed_facts"] == []
    assert summary["review_required"][0]["object"] == "신뢰도 0.8~0.95 후보 구간(확정 근거 제외)"
    assert summary["evidence_checklist"][0]["name"] == "수술확인서"
    assert summary["review_actions"][0]["order"] == 1
