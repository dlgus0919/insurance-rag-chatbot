from __future__ import annotations

import json
from pathlib import Path

from src.graph.extractors import PolicyReviewExtractor
from src.graph.schema import EdgeType, NodeType
from src.graph.store import GraphStore


def test_policy_review_extractor_creates_clause_and_links(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunk = {
        "id": "약관_ch_0001",
        "text": "제2조 합병증 치료는 미용 목적 수술 후 발생한 경우 보상하지 않는다. 진단서와 세부내역서를 확인해야 한다.",
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
    chunks_path.write_text(json.dumps(chunk, ensure_ascii=False) + "\n", encoding="utf-8")

    extractor = PolicyReviewExtractor(store)
    extractor.extract(chunks_path)

    clauses = store.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.PolicyClause.value,))
    assert len(clauses) == 1
    clause = clauses[0]
    props = json.loads(clause["properties_json"])
    assert props["clause_type"] == "exclusion"
    assert props["decision_polarity"] == "exclusion"
    assert "ExclusionRule" in props["rule_types"]
    assert "EvidenceGateRule" in props["rule_types"]
    assert props["rule_summary"].startswith("ExclusionRule")

    complication_edges = store.query(
        "SELECT * FROM graph_edges WHERE source_node_id = ? AND edge_type = ?",
        (clause["node_id"], EdgeType.RELATES_TO_COMPLICATION.value),
    )
    assert complication_edges

    evidence_edges = store.query(
        "SELECT * FROM graph_edges WHERE source_node_id = ? AND edge_type = ?",
        (clause["node_id"], EdgeType.REQUIRES_EVIDENCE.value),
    )
    assert len(evidence_edges) >= 2

    decision_edges = store.query(
        "SELECT * FROM graph_edges WHERE source_node_id = ? AND edge_type = ?",
        (clause["node_id"], EdgeType.HAS_DECISION.value),
    )
    assert decision_edges


def test_policy_review_extractor_adds_rule_layer_properties(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": "제3조 도수치료는 연간 50회 한도이며 회당 공제금액을 적용한다. 세부내역서를 제출해야 한다.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 71,
                "page_end": 71,
                "section": "제3조(보상한도와 공제)",
                "codes": [],
            },
        },
        {
            "id": "약관_ch_0002",
            "text": "제4조 보험금 지급사유에 해당하는 경우 보험금을 지급한다.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 72,
                "page_end": 72,
                "section": "제4조(보험금의 지급사유)",
                "codes": [],
            },
        },
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")

    PolicyReviewExtractor(store).extract(chunks_path)

    rows = store.query("SELECT * FROM graph_nodes WHERE node_type = ? ORDER BY canonical_name", (NodeType.PolicyClause.value,))
    props_by_title = {json.loads(row["properties_json"])["clause_title"]: json.loads(row["properties_json"]) for row in rows}

    limit_props = props_by_title["제3조(보상한도와 공제)"]
    assert limit_props["clause_type"] == "limit_rule"
    assert "LimitRule" in limit_props["rule_types"]
    assert "DeductibleRule" in limit_props["rule_types"]
    assert "EvidenceGateRule" in limit_props["rule_types"]

    coverage_props = props_by_title["제4조(보험금의 지급사유)"]
    assert coverage_props["clause_type"] == "coverage_trigger"
    assert coverage_props["rule_types"] == ["CoverageTriggerRule"]
