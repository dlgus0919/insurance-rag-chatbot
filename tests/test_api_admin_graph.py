from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.build_graph_visualization_snapshot import build_snapshot
from src.api.main import create_app
from src.api.routes import admin_graph
from src.auth.users import User


def _user(role: str) -> User:
    return User(
        username=role,
        password_hash="hash",
        role=role,
        display_name=role,
        created_at="2026-07-15T00:00:00+00:00",
        password_updated_at="2026-07-15T00:00:00+00:00",
    )


def _make_graph(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE graph_nodes (
                node_id TEXT PRIMARY KEY, node_type TEXT, canonical_name TEXT,
                normalized_name TEXT, properties_json TEXT, confidence REAL,
                created_by TEXT, updated_at TEXT
            );
            CREATE TABLE graph_aliases (
                alias_id TEXT PRIMARY KEY, node_id TEXT, alias TEXT,
                normalized_alias TEXT, source TEXT, confidence REAL
            );
            CREATE TABLE graph_edges (
                edge_id TEXT PRIMARY KEY, source_node_id TEXT, target_node_id TEXT,
                edge_type TEXT, properties_json TEXT, confidence REAL,
                source_evidence_id TEXT, created_by TEXT, updated_at TEXT
            );
            CREATE TABLE graph_evidence (
                evidence_id TEXT PRIMARY KEY, doc_short TEXT, page_start INTEGER,
                page_end INTEGER
            );
            CREATE TABLE graph_node_evidence (
                node_id TEXT, evidence_id TEXT, role TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO graph_nodes VALUES (?, ?, ?, ?, '{}', 1.0, 'test', '')",
            [
                ("category", "SurgeryCategory", "수술 분류", "수술분류"),
                ("procedure", "SurgeryProcedure", "수술 A", "수술a"),
                ("condition", "ClaimCondition", "청구 조건", "청구조건"),
            ],
        )
        conn.executemany(
            "INSERT INTO graph_edges VALUES (?, ?, ?, ?, ?, 1.0, NULL, 'test', '')",
            [
                ("hierarchy", "procedure", "category", "HAS_CATEGORY", "{}"),
                ("related", "procedure", "condition", "HAS_DECISION", "{}"),
            ],
        )
        conn.execute("INSERT INTO graph_aliases VALUES ('alias-1', 'procedure', '수술가', '수술가', 'test', 1.0)")
        conn.execute("INSERT INTO graph_evidence VALUES ('evidence-1', '약관', 10, 11)")
        conn.execute("INSERT INTO graph_node_evidence VALUES ('procedure', 'evidence-1', 'source')")


def _client(graph_path: Path, snapshot_path: Path, monkeypatch, role: str = "admin") -> TestClient:
    monkeypatch.setattr(admin_graph.config, "GRAPH_INDEX_PATH", graph_path)
    monkeypatch.setattr(admin_graph.config, "GRAPH_VIZ_SNAPSHOT_PATH", snapshot_path)
    app = create_app()
    from src.api.deps import current_user

    app.dependency_overrides[current_user] = lambda: _user(role)
    return TestClient(app)


def test_graph_overview_and_focus_are_bounded_and_read_only(tmp_path: Path, monkeypatch) -> None:
    graph_path = tmp_path / "graph.sqlite"
    snapshot_path = tmp_path / "graph-viz.json"
    _make_graph(graph_path)
    build_snapshot(graph_path, snapshot_path, node_limit=3, edge_limit=3)
    client = _client(graph_path, snapshot_path, monkeypatch)

    overview = client.get("/api/admin/graph/overview", params={"node_limit": 150, "edge_limit": 300})
    focus = client.get("/api/admin/graph/nodes/category/neighborhood", params={"child_depth": 3})
    detail = client.get("/api/admin/graph/nodes/procedure")

    assert overview.status_code == 200
    assert len(overview.json()["nodes"]) <= 150
    assert len(overview.json()["edges"]) <= 300
    assert overview.json()["meta"]["hierarchy_policy"] == "category_and_explicit_subclass_only"
    assert focus.status_code == 200
    assert {edge["semantic_role"] for edge in focus.json()["edges"]} == {"child"}
    assert detail.status_code == 200
    assert detail.json()["evidence"] == [{"doc_short": "약관", "page_start": 10, "page_end": 11}]
    assert "properties_json" not in detail.text

    search = client.get("/api/admin/graph/search", params={"q": "수술", "limit": 20})
    assert search.status_code == 200
    assert search.json()["total"] == len(search.json()["items"])
    assert "limit" not in search.json()


def test_graph_search_requires_admin_and_reports_unavailable_snapshot(tmp_path: Path, monkeypatch) -> None:
    graph_path = tmp_path / "graph.sqlite"
    snapshot_path = tmp_path / "missing.json"
    _make_graph(graph_path)

    employee_client = _client(graph_path, snapshot_path, monkeypatch, role="employee")
    denied = employee_client.get("/api/admin/graph/search", params={"q": "수술"})
    assert denied.status_code == 403

    admin_client = _client(graph_path, snapshot_path, monkeypatch)
    unavailable = admin_client.get("/api/admin/graph/overview")
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "GRAPH_VISUALIZATION_UNAVAILABLE"
