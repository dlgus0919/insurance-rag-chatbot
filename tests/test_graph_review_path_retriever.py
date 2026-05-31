from __future__ import annotations

import json
from pathlib import Path

from src.graph.extractors import PolicyReviewExtractor
from src.graph.retriever import GraphRetriever
from src.graph.store import GraphStore


def test_graph_retriever_builds_complication_review_path(tmp_path: Path) -> None:
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
                "page_start": 80,
                "page_end": 80,
                "section": "제2조(보상하지 않는 손해)",
                "codes": [],
            },
        }
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    retriever = GraphRetriever(db_path)
    result = retriever.retrieve("미용 목적 쌍꺼풀 수술 후 염증이 생겼습니다. 합병증 치료비를 실손으로 받을 수 있나요?")

    assert result.review_paths
    path = result.review_paths[0]
    assert path.path_type == "complication_review"
    assert path.status in {"confirmed", "review_required"}
    assert any(step.object == "합병증" for step in path.steps if step.source == "session")
    assert not any("당뇨" in (step.object or "") and "망막병증" in (step.object or "") for step in path.steps)


def test_graph_retriever_does_not_confirm_wrong_topic_exclusion(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": "제1조 실손 합병증 치료는 보상하지 않는다.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 10,
                "page_end": 10,
                "section": "제1조(보상하지 않는 손해)",
                "codes": [],
            },
        },
        {
            "id": "약관_ch_0002",
            "text": "제2조 합병증 특약은 진단서와 세부내역서를 제출한 경우 추가 심사 필요.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "특약 약관",
                "pdf_filename": "special.pdf",
                "page_start": 11,
                "page_end": 11,
                "section": "제2조(합병증 특약)",
                "codes": [],
            },
        },
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    retriever = GraphRetriever(db_path)
    result = retriever.retrieve("당뇨 진단 후 합병증 특약 보상이 되나요?")

    path = next(path for path in result.review_paths if path.path_type == "complication_review")
    assert path.status == "review_required"
    assert any(step.object == "면책" and step.status == "candidate" for step in path.steps)
    assert not any(step.object == "면책" and step.status == "confirmed" for step in path.steps)
