from __future__ import annotations

import json
from pathlib import Path

from src.graph.extractors import PolicyReviewExtractor
from src.graph.query_planner import GraphQueryPlanner
from src.graph.retriever import GraphRetriever
from src.graph.store import GraphStore


def _write_chunks(path: Path, chunks: list[dict]) -> None:
    path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")


def _build_one_disease_graph(tmp_path: Path) -> Path:
    db_path = tmp_path / "graph.sqlite"
    chunks_path = tmp_path / "chunks.jsonl"
    _write_chunks(
        chunks_path,
        [
            {
                "id": "표준약관_ch_one_disease_0001",
                "text": (
                    "제3조 하나의 질병이란 발생 원인이 동일한 질병을 말하며, "
                    "의학상 중요한 관련이 있는 질병은 하나의 질병으로 간주합니다. "
                    "하나의 질병으로 2회 이상 치료를 받는 경우에는 이를 하나의 질병으로 봅니다. "
                    "질병의 치료 중에 발생된 합병증 또는 새로 발견된 질병의 치료가 병행된 경우도 검토합니다."
                ),
                "metadata": {
                    "doc_short": "표준약관",
                    "doc_name": "실손 표준약관",
                    "pdf_filename": "standard.pdf",
                    "page_start": 350,
                    "page_end": 350,
                    "section": "제3조(보장종목별 보상내용)",
                    "codes": [],
                },
            }
        ],
    )
    PolicyReviewExtractor(GraphStore(db_path)).extract(chunks_path)
    return db_path


def test_query_planner_detects_one_disease_review_intent() -> None:
    plan = GraphQueryPlanner().plan("같은 질병으로 두 번 통원하면 하나의 질병으로 보나요?")

    assert plan.disease_grouping_requested is True
    assert plan.same_disease_claimed is True
    assert "하나의 질병" in plan.claim_unit_terms
    assert "one_disease_policy_lookup" in plan.intents
    assert "disease_grouping_review" in plan.intents


def test_graph_retriever_returns_one_disease_review_path(tmp_path: Path) -> None:
    db_path = _build_one_disease_graph(tmp_path)

    result = GraphRetriever(db_path).retrieve("당뇨 진단 후 합병증 치료를 받았는데 하나의 질병으로 보나요?")

    paths = [path for path in result.review_paths if path.path_type == "one_disease_review"]
    assert paths
    path = paths[0]
    assert path.status == "review_required"
    assert "자동 확정하지 않고" in path.summary
    assert any(step.relation == "DEFINES_CLAIM_UNIT" and step.object == "하나의 질병" for step in path.steps)
    assert any(step.relation == "HAS_GROUPING_RULE" for step in path.steps)
    assert "진단서" in path.required_documents
