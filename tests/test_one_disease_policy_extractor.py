from __future__ import annotations

import json
from pathlib import Path

from src.graph.extractors import PolicyReviewExtractor
from src.graph.schema import EdgeType, NodeType
from src.graph.store import GraphStore


def _write_chunks(path: Path, chunks: list[dict]) -> None:
    path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")


def test_policy_review_extractor_creates_one_disease_grouping_nodes(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    chunks_path = tmp_path / "chunks.jsonl"
    store = GraphStore(db_path)
    _write_chunks(
        chunks_path,
        [
            {
                "id": "표준약관_ch_one_disease_0001",
                "text": (
                    "제3조 하나의 질병이란 발생 원인이 동일한 질병을 말하며, "
                    "의학상 중요한 관련이 있는 질병은 하나의 질병으로 간주합니다. "
                    "하나의 질병으로 2회 이상 치료를 받는 경우에도 하나의 질병으로 봅니다. "
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

    PolicyReviewExtractor(store).extract(chunks_path)

    for node_type in (
        NodeType.ClaimUnitConcept,
        NodeType.DiseaseGroupingRule,
        NodeType.DiseaseRelationCriterion,
        NodeType.TreatmentEpisodeContext,
    ):
        assert store.query("SELECT * FROM graph_nodes WHERE node_type = ?", (node_type.value,))

    clause = store.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.PolicyClause.value,))[0]
    edge_types = {
        row["edge_type"]
        for row in store.query("SELECT edge_type FROM graph_edges WHERE source_node_id = ?", (clause["node_id"],))
    }
    assert EdgeType.DEFINES_CLAIM_UNIT.value in edge_types
    assert EdgeType.HAS_GROUPING_RULE.value in edge_types
    assert EdgeType.REQUIRES_GROUPING_REVIEW.value in edge_types

    grouping_rule = store.query(
        "SELECT * FROM graph_nodes WHERE node_type = ? AND canonical_name = ?",
        (NodeType.DiseaseGroupingRule.value, "의학상 중요한 관련 기준"),
    )[0]
    grouping_edges = {
        row["edge_type"]
        for row in store.query("SELECT edge_type FROM graph_edges WHERE source_node_id = ?", (grouping_rule["node_id"],))
    }
    assert EdgeType.HAS_RELATION_CRITERION.value in grouping_edges
    assert EdgeType.APPLIES_TO_CLAIM_UNIT.value in grouping_edges
    assert EdgeType.REQUIRES_GROUPING_EVIDENCE.value in grouping_edges
