from __future__ import annotations

import json
from pathlib import Path

from src.graph.build import _ingest_rule_links
from src.graph.store import GraphStore


def test_ingest_rule_links_creates_traceability_nodes(tmp_path: Path) -> None:
    links_path = tmp_path / "rule_links.active.json"
    links_path.write_text(
        json.dumps(
            [
                {
                    "rule_id": "deductible.test.5th.outpatient.benefit",
                    "source_refs": ["policy_chunk:chunk-123"],
                    "ontology_refs": ["cov.indemnity_medical"],
                    "graph_refs": ["source_chunk:chunk-123"],
                    "link_status": "active",
                },
                {
                    "rule_id": "deductible.pending",
                    "source_refs": ["policy_chunk:chunk-999"],
                    "ontology_refs": ["cov.pending"],
                    "link_status": "candidate",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = GraphStore(tmp_path / "graph.sqlite", build_mode=True)

    try:
        _ingest_rule_links(store, links_path)
        nodes = {
            row["node_id"]: row["node_type"]
            for row in store.query("SELECT node_id, node_type FROM graph_nodes")
        }
        edge_types = {
            row["edge_type"]
            for row in store.query("SELECT edge_type FROM graph_edges")
        }
        evidence = store.query("SELECT chunk_id FROM graph_evidence WHERE evidence_id = ?", ("evidence:chunk-123",))

        assert nodes["deductible_rule:deductible.test.5th.outpatient.benefit"] == "DeductibleRule"
        assert nodes["source_chunk:chunk-123"] == "DocumentSection"
        assert nodes["ontology:cov.indemnity_medical"] == "DecisionConcept"
        assert "deductible_rule:deductible.pending" not in nodes
        assert edge_types == {"HAS_CANONICAL_SOURCE", "HAS_DEDUCTIBLE_RULE"}
        assert evidence[0]["chunk_id"] == "chunk-123"
    finally:
        store.close()
