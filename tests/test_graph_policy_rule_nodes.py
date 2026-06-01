from __future__ import annotations

import json
from pathlib import Path

from src.graph.extractors import PolicyReviewExtractor
from src.graph.schema import EdgeType, NodeType
from src.graph.store import GraphStore


def _write_chunks(path: Path, chunks: list[dict]) -> None:
    path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")


def test_policy_review_extractor_creates_stage2_rule_nodes_and_edges(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    _write_chunks(
        chunks_path,
        [
            {
                "id": "약관_ch_rule_0001",
                "text": (
                    "제3조 미용 목적 치료는 보상하지 않는다. 도수치료는 연간 50회 한도이며 "
                    "5세대 실손에서는 공제금액을 적용한다. 진료비 영수증과 진료비 세부내역서를 제출해야 한다."
                ),
                "metadata": {
                    "doc_short": "약관",
                    "doc_name": "실손 약관",
                    "pdf_filename": "medical.pdf",
                    "page_start": 71,
                    "page_end": 71,
                    "section": "제3조(보상한도와 공제)",
                    "codes": [],
                },
            }
        ],
    )

    PolicyReviewExtractor(store).extract(chunks_path)

    for node_type in (
        NodeType.ExclusionReason,
        NodeType.BenefitLimit,
        NodeType.DeductibleRule,
        NodeType.RequiredDocument,
        NodeType.CoordinationRule,
        NodeType.RenewalOrGenerationRule,
    ):
        rows = store.query("SELECT * FROM graph_nodes WHERE node_type = ?", (node_type.value,))
        assert rows, node_type

    clause = store.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.PolicyClause.value,))[0]
    expected_edges = {
        EdgeType.HAS_EXCLUSION_REASON,
        EdgeType.HAS_BENEFIT_LIMIT,
        EdgeType.HAS_DEDUCTIBLE_RULE,
        EdgeType.REQUIRES_DOCUMENT,
        EdgeType.HAS_GENERATION_RULE,
    }
    edges = store.query("SELECT edge_type FROM graph_edges WHERE source_node_id = ?", (clause["node_id"],))
    edge_types = {row["edge_type"] for row in edges}
    assert {edge.value for edge in expected_edges}.issubset(edge_types)


def test_policy_review_extractor_links_coordination_rule(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    _write_chunks(
        chunks_path,
        [
            {
                "id": "약관_ch_coord_0001",
                "text": "제4조 자동차보험 또는 산재보험으로 이미 보상받은 경우 타 보험 보상 내역을 확인한다.",
                "metadata": {
                    "doc_short": "약관",
                    "doc_name": "실손 약관",
                    "pdf_filename": "medical.pdf",
                    "page_start": 82,
                    "page_end": 82,
                    "section": "제4조(중복 보상 조정)",
                    "codes": [],
                },
            }
        ],
    )

    PolicyReviewExtractor(store).extract(chunks_path)

    clause = store.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.PolicyClause.value,))[0]
    rows = store.query(
        """
        SELECT dst.canonical_name
        FROM graph_edges e
        JOIN graph_nodes dst ON e.target_node_id = dst.node_id
        WHERE e.source_node_id = ? AND e.edge_type = ?
        ORDER BY dst.canonical_name
        """,
        (clause["node_id"], EdgeType.HAS_COORDINATION_RULE.value),
    )
    names = {row["canonical_name"] for row in rows}
    assert "자동차보험 처리 후 실손 청구" in names
    assert "산재보험 처리 후 실손 청구" in names
