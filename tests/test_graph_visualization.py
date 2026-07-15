from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.build_graph_visualization_snapshot import build_snapshot
from scripts.profile_graph_visualization import profile_graph
from src.graph.visualization import GraphVisualizationService


def make_graph(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE graph_nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT,
                canonical_name TEXT,
                normalized_name TEXT,
                properties_json TEXT,
                confidence REAL,
                created_by TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE graph_aliases (
                alias_id TEXT PRIMARY KEY,
                node_id TEXT,
                alias TEXT,
                normalized_alias TEXT,
                source TEXT,
                confidence REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE graph_edges (
                edge_id TEXT PRIMARY KEY,
                source_node_id TEXT,
                target_node_id TEXT,
                edge_type TEXT,
                properties_json TEXT,
                confidence REAL,
                source_evidence_id TEXT,
                created_by TEXT,
                updated_at TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO graph_nodes VALUES (?, ?, ?, ?, '{}', 1.0, 'test', '')",
            [
                ("root", "ClaimCondition", "청구 조건", "청구 조건"),
                ("decision", "DecisionConcept", "지급 결정", "지급결정"),
                ("evidence", "EvidenceRequirement", "필요 근거", "필요 근거"),
                ("isolated", "Document", "고립 문서", "고립 문서"),
                ("category", "SurgeryCategory", "수술 분류", "수술분류"),
                ("subcategory", "SurgeryCategory", "하위 분류", "하위분류"),
                ("procedure", "SurgeryProcedure", "수술 A", "수술a"),
            ],
        )
        conn.executemany(
            "INSERT INTO graph_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("e1", "root", "decision", "HAS_DECISION", "{}", 1.0, None, "test", ""),
                ("e2", "decision", "evidence", "REQUIRES_EVIDENCE", "{}", 1.0, None, "test", ""),
                ("e3", "procedure", "category", "HAS_CATEGORY", "{}", 1.0, None, "test", ""),
                (
                    "e4",
                    "subcategory",
                    "category",
                    "SAME_CATEGORY_AS",
                    '{"relationship":"subclass_of"}',
                    1.0,
                    None,
                    "test",
                    "",
                ),
            ],
        )


def test_profile_graph_reports_types_pairs_degree_and_redacted_components(tmp_path: Path) -> None:
    path = tmp_path / "graph.sqlite"
    make_graph(path)

    result = profile_graph(path, sample_limit=2)

    assert result["node_type_counts"] == {
        "ClaimCondition": 1,
        "DecisionConcept": 1,
        "Document": 1,
        "EvidenceRequirement": 1,
        "SurgeryCategory": 2,
        "SurgeryProcedure": 1,
    }
    assert result["edge_type_counts"] == {
        "HAS_CATEGORY": 1,
        "HAS_DECISION": 1,
        "REQUIRES_EVIDENCE": 1,
        "SAME_CATEGORY_AS": 1,
    }
    assert result["edge_type_pairs"]["HAS_DECISION"] == {
        "ClaimCondition->DecisionConcept": 1
    }
    assert result["degree"]["max"] == 2
    assert result["degree"]["isolated_nodes"] == 1
    assert result["components"]["nonisolated_count"] == 2
    assert "top_degree_node_ids" not in result


def test_overview_is_deterministic_and_enforces_bounds(tmp_path: Path) -> None:
    path = tmp_path / "graph.sqlite"
    make_graph(path)
    service = GraphVisualizationService(path)

    graph = service.overview(node_limit=6, edge_limit=1)

    assert graph.nodes[0].node_id == "category"
    assert len(graph.nodes) == 6
    assert len(graph.edges) == 1
    assert graph.meta["node_limit"] == 6
    assert graph.meta["edge_limit"] == 1
    assert graph.meta["truncated_edges"] >= 1


def test_neighborhood_only_uses_evidence_backed_hierarchy_edges(tmp_path: Path) -> None:
    path = tmp_path / "graph.sqlite"
    make_graph(path)
    service = GraphVisualizationService(path)

    category_graph = service.neighborhood(
        "category", child_depth=2, node_limit=10, edge_limit=10, include_related=False
    )
    procedure_graph = service.neighborhood(
        "procedure", child_depth=2, node_limit=10, edge_limit=10, include_related=False
    )

    assert {node.node_id for node in category_graph.nodes} == {
        "category",
        "procedure",
        "subcategory",
    }
    assert {edge.semantic_role for edge in category_graph.edges} == {"child"}
    assert {node.node_id for node in procedure_graph.nodes} == {"procedure", "category"}
    assert {edge.semantic_role for edge in procedure_graph.edges} == {"parent"}


def test_search_prefers_exact_name_then_alias(tmp_path: Path) -> None:
    path = tmp_path / "graph.sqlite"
    make_graph(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO graph_aliases VALUES ('a1', 'decision', '결정', '결정', 'test', 1.0)"
        )
    service = GraphVisualizationService(path)

    assert service.search("지급 결정", 20)[0].node_id == "decision"
    assert service.search("결정", 20)[0].node_id == "decision"


def test_build_snapshot_writes_bounded_public_graph_payload(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.sqlite"
    snapshot_path = tmp_path / "insurance_graph_viz.json"
    make_graph(graph_path)

    payload = build_snapshot(graph_path, snapshot_path, node_limit=6, edge_limit=1)

    persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload == persisted
    assert persisted["schema_version"] == 1
    assert len(persisted["nodes"]) <= 6
    assert len(persisted["edges"]) <= 1
    assert "graph_path" not in json.dumps(persisted, ensure_ascii=False)
