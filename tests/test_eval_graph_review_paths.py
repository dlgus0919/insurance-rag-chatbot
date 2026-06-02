import json
from pathlib import Path

from scripts.eval_graph_review_paths import evaluate_four_sections_completeness, run_eval
from src.graph.extractors import PolicyReviewExtractor
from src.graph.query_planner import GraphQueryPlan
from src.graph.retriever import GraphEvidence, GraphFact, GraphRetrievalResult
from src.graph.store import GraphStore


def test_eval_graph_review_paths_passes_fixture(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": "제2조 미용 목적 수술 후 합병증 치료는 보상하지 않는다. 진단서와 세부내역서를 확인해야 한다.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 38,
                "page_end": 38,
                "section": "제2조(보상하지 않는 손해)",
                "codes": [],
            },
        }
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    eval_path = tmp_path / "eval.jsonl"
    eval_path.write_text(
        json.dumps(
            {
                "id": "fixture",
                "question": "미용 목적 쌍꺼풀 수술 후 염증이 생겼습니다. 합병증 치료비를 실손으로 받을 수 있나요?",
                "expected_path_types": ["complication_review", "claim_condition_review"],
                "allowed_statuses": ["confirmed", "review_required"],
                "required_session_assertions": ["미용 목적", "합병증"],
                "required_review_actions_any": ["진단서 요청", "세부내역서 요청"],
                "required_evidence_any": ["진단서", "세부내역서"],
                "forbidden_text": ["당뇨 -> 망막병증"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_eval(db_path, eval_path)

    assert summary["passed"] == 1
    assert summary["failed"] == 0


def test_evaluate_four_sections_completeness_tracks_candidate_isolation() -> None:
    result = GraphRetrievalResult(
        plan=GraphQueryPlan(intents=["session_claim_path_review"]),
        facts=[
            GraphFact(
                subject="확정 수술",
                relation="HAS_GRADE",
                object="2종",
                confidence=1.0,
                status="confirmed",
                evidence=[GraphEvidence(evidence_id="ev-1", doc_short="실무가이드", page_start=12)],
            ),
            GraphFact(
                subject="후보 지급비율",
                relation="PAYS_BY_RATIO",
                object="100%",
                confidence=0.9,
                status="candidate",
            ),
        ],
        required_evidence=["진단서"],
        review_actions=["원문 확인"],
    )

    summary = evaluate_four_sections_completeness([{"id": "case", "question": "질문", "graph_result": result}])

    assert summary["confirmed_facts_completeness"] == 1.0
    assert summary["review_required_completeness"] == 1.0
    assert summary["evidence_checklist_completeness"] == 1.0
    assert summary["review_actions_completeness"] == 1.0
    assert summary["candidate_isolation_rate"] == 1.0
    assert summary["samples_with_all_sections"] == 1
