"""Read-only, bounded GraphDB queries for the administrator visualization."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.graph.normalizer import normalize_name

DEFAULT_OVERVIEW_NODES = 120
DEFAULT_OVERVIEW_EDGES = 240
MAX_OVERVIEW_NODES = 150
MAX_OVERVIEW_EDGES = 300
DEFAULT_FOCUS_NODES = 180
DEFAULT_FOCUS_EDGES = 360
MAX_FOCUS_NODES = 250
MAX_FOCUS_EDGES = 500
MAX_SEARCH_RESULTS = 20
MAX_CHILD_DEPTH = 3

# DGX profile evidence: the source node is the child and the target is its
# category. SAME_CATEGORY_AS is hierarchy only when its explicit property says
# subclass_of; equivalent categories remain ordinary related edges.
HIERARCHY_EDGE_DIRECTIONS: dict[str, str] = {
    "HAS_CATEGORY": "child_to_parent",
    "SAME_CATEGORY_AS": "child_to_parent",
}

SEMANTIC_TYPE_WEIGHT = {
    "SurgeryCategory": 8.0,
    "CoverageItem": 8.0,
    "DecisionConcept": 7.0,
    "ClaimCondition": 7.0,
    "PolicyBenefitRule": 7.0,
    "EvidenceRequirement": 6.0,
    "DeductibleRule": 6.0,
    "ClaimUnitConcept": 6.0,
    "DiseaseGroupingRule": 5.0,
    "SurgeryProcedure": 4.0,
    "Document": 3.0,
}


@dataclass(frozen=True)
class VizNode:
    node_id: str
    label: str
    node_type: str
    degree: int
    score: float
    confidence: float


@dataclass(frozen=True)
class VizEdge:
    edge_id: str
    source: str
    target: str
    edge_type: str
    semantic_role: Literal["parent", "child", "related", "overview"]


@dataclass(frozen=True)
class VizGraph:
    nodes: list[VizNode]
    edges: list[VizEdge]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VizSearchResult:
    node_id: str
    label: str
    node_type: str
    degree: int
    match_kind: Literal["exact", "alias", "prefix", "contains"]


def core_score(
    node_type: str,
    degree: int,
    parent_count: int,
    child_count: int,
    confidence: float,
) -> float:
    root_bonus = 4.0 if parent_count == 0 and child_count > 0 else 0.0
    hub_bonus = min(12.0, math.sqrt(degree))
    return round(
        SEMANTIC_TYPE_WEIGHT.get(node_type, 1.0) + root_bonus + hub_bonus + confidence,
        6,
    )


def _properties(raw_value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(raw_value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_hierarchy_edge(row: sqlite3.Row) -> bool:
    edge_type = str(row["edge_type"])
    if edge_type == "HAS_CATEGORY":
        return True
    return (
        edge_type == "SAME_CATEGORY_AS"
        and _properties(row["properties_json"]).get("relationship") == "subclass_of"
    )


def _placeholders(values: list[str]) -> str:
    return ", ".join("?" for _ in values)


class GraphVisualizationService:
    """Serve small graph slices from a read-only SQLite connection."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError("GraphDB file is unavailable")
        conn = sqlite3.connect(f"file:{self.db_path.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _bounded(value: int, maximum: int) -> int:
        return max(1, min(int(value), maximum))

    @staticmethod
    def _node_from_row(row: sqlite3.Row, degree: int, score: float) -> VizNode:
        return VizNode(
            node_id=row["node_id"],
            label=row["canonical_name"],
            node_type=row["node_type"],
            degree=degree,
            score=score,
            confidence=float(row["confidence"] or 0.0),
        )

    @staticmethod
    def _edge_from_row(
        row: sqlite3.Row,
        role: Literal["parent", "child", "related", "overview"],
    ) -> VizEdge:
        return VizEdge(
            edge_id=row["edge_id"],
            source=row["source_node_id"],
            target=row["target_node_id"],
            edge_type=row["edge_type"],
            semantic_role=role,
        )

    def _connected_node_rows(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return conn.execute(
            """
            WITH endpoint_degree AS (
                SELECT node_id, COUNT(*) AS degree
                FROM (
                    SELECT source_node_id AS node_id FROM graph_edges
                    UNION ALL
                    SELECT target_node_id AS node_id FROM graph_edges
                ) endpoints
                GROUP BY node_id
            )
            SELECT n.*, endpoint_degree.degree
            FROM endpoint_degree
            JOIN graph_nodes n ON n.node_id = endpoint_degree.node_id
            """
        ).fetchall()

    @staticmethod
    def _all_edges(conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return conn.execute(
            """
            SELECT edge_id, source_node_id, target_node_id, edge_type, properties_json
            FROM graph_edges
            ORDER BY edge_type, source_node_id, target_node_id, edge_id
            """
        ).fetchall()

    @staticmethod
    def _hierarchy_counts(edges: list[sqlite3.Row]) -> tuple[dict[str, int], dict[str, int]]:
        parent_counts: dict[str, int] = {}
        child_counts: dict[str, int] = {}
        for edge in edges:
            if not _is_hierarchy_edge(edge):
                continue
            parent_counts[edge["source_node_id"]] = parent_counts.get(edge["source_node_id"], 0) + 1
            child_counts[edge["target_node_id"]] = child_counts.get(edge["target_node_id"], 0) + 1
        return parent_counts, child_counts

    def overview(self, node_limit: int = DEFAULT_OVERVIEW_NODES, edge_limit: int = DEFAULT_OVERVIEW_EDGES) -> VizGraph:
        node_limit = self._bounded(node_limit, MAX_OVERVIEW_NODES)
        edge_limit = self._bounded(edge_limit, MAX_OVERVIEW_EDGES)
        with self._connect() as conn:
            rows = self._connected_node_rows(conn)
            all_edges = self._all_edges(conn)

        parent_counts, child_counts = self._hierarchy_counts(all_edges)
        candidates: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            degree = int(row["degree"])
            score = core_score(
                row["node_type"],
                degree,
                parent_counts.get(row["node_id"], 0),
                child_counts.get(row["node_id"], 0),
                float(row["confidence"] or 0.0),
            )
            candidates.append((score, row))
        candidates.sort(
            key=lambda item: (
                -item[0],
                -int(item[1]["degree"]),
                item[1]["node_type"],
                item[1]["node_id"],
            )
        )

        per_type_cap = max(3, node_limit // 5)
        selected: list[tuple[float, sqlite3.Row]] = []
        type_counts: dict[str, int] = {}
        deferred: list[tuple[float, sqlite3.Row]] = []
        for candidate in candidates:
            node_type = candidate[1]["node_type"]
            if type_counts.get(node_type, 0) >= per_type_cap:
                deferred.append(candidate)
                continue
            selected.append(candidate)
            type_counts[node_type] = type_counts.get(node_type, 0) + 1
            if len(selected) == node_limit:
                break
        if len(selected) < node_limit:
            selected.extend(deferred[: node_limit - len(selected)])

        selected_ids = {row["node_id"] for _, row in selected}
        hierarchy_edges = [
            edge
            for edge in all_edges
            if _is_hierarchy_edge(edge)
            and edge["source_node_id"] in selected_ids
            and edge["target_node_id"] in selected_ids
        ]
        hierarchy_edges.sort(key=lambda edge: (edge["edge_type"], edge["edge_id"]))
        visible_edges = hierarchy_edges[:edge_limit]
        nodes = [self._node_from_row(row, int(row["degree"]), score) for score, row in selected]
        return VizGraph(
            nodes=nodes,
            edges=[self._edge_from_row(edge, "overview") for edge in visible_edges],
            meta={
                "node_limit": node_limit,
                "edge_limit": edge_limit,
                "truncated_nodes": max(0, len(candidates) - len(selected)),
                "truncated_edges": max(0, len(hierarchy_edges) - len(visible_edges)),
                "hierarchy_policy": "category_and_explicit_subclass_only",
            },
        )

    def _node_rows_by_id(self, conn: sqlite3.Connection, node_ids: list[str]) -> dict[str, sqlite3.Row]:
        if not node_ids:
            return {}
        placeholders = _placeholders(node_ids)
        rows = conn.execute(
            f"SELECT * FROM graph_nodes WHERE node_id IN ({placeholders})", node_ids
        ).fetchall()
        return {row["node_id"]: row for row in rows}

    def _degree_map(self, conn: sqlite3.Connection, node_ids: list[str]) -> dict[str, int]:
        if not node_ids:
            return {}
        placeholders = _placeholders(node_ids)
        query = f"""
            SELECT node_id, COUNT(*) AS degree
            FROM (
                SELECT source_node_id AS node_id FROM graph_edges WHERE source_node_id IN ({placeholders})
                UNION ALL
                SELECT target_node_id AS node_id FROM graph_edges WHERE target_node_id IN ({placeholders})
            ) endpoints
            GROUP BY node_id
        """
        rows = conn.execute(query, [*node_ids, *node_ids]).fetchall()
        return {row["node_id"]: int(row["degree"]) for row in rows}

    def _edges_by_source(self, conn: sqlite3.Connection, node_ids: list[str]) -> list[sqlite3.Row]:
        if not node_ids:
            return []
        placeholders = _placeholders(node_ids)
        return conn.execute(
            f"""
            SELECT edge_id, source_node_id, target_node_id, edge_type, properties_json
            FROM graph_edges
            WHERE source_node_id IN ({placeholders})
            ORDER BY edge_type, target_node_id, edge_id
            """,
            node_ids,
        ).fetchall()

    def _edges_by_target(self, conn: sqlite3.Connection, node_ids: list[str]) -> list[sqlite3.Row]:
        if not node_ids:
            return []
        placeholders = _placeholders(node_ids)
        return conn.execute(
            f"""
            SELECT edge_id, source_node_id, target_node_id, edge_type, properties_json
            FROM graph_edges
            WHERE target_node_id IN ({placeholders})
            ORDER BY edge_type, source_node_id, edge_id
            """,
            node_ids,
        ).fetchall()

    def neighborhood(
        self,
        node_id: str,
        child_depth: int = 1,
        node_limit: int = DEFAULT_FOCUS_NODES,
        edge_limit: int = DEFAULT_FOCUS_EDGES,
        include_related: bool = False,
    ) -> VizGraph:
        child_depth = self._bounded(child_depth, MAX_CHILD_DEPTH)
        node_limit = self._bounded(node_limit, MAX_FOCUS_NODES)
        edge_limit = self._bounded(edge_limit, MAX_FOCUS_EDGES)
        with self._connect() as conn:
            records = self._node_rows_by_id(conn, [node_id])
            if node_id not in records:
                raise KeyError(node_id)
            selected_ids = {node_id}
            selected_edges: list[tuple[sqlite3.Row, Literal["parent", "child", "related"]]] = []
            seen_edges: set[str] = set()
            truncated_nodes = 0
            truncated_edges = 0

            def add_edge(edge: sqlite3.Row, role: Literal["parent", "child", "related"]) -> bool:
                nonlocal truncated_nodes, truncated_edges
                if edge["edge_id"] in seen_edges:
                    return True
                candidate_ids = {edge["source_node_id"], edge["target_node_id"]}
                missing_ids = candidate_ids - selected_ids
                if len(selected_edges) >= edge_limit:
                    truncated_edges += 1
                    return False
                if len(selected_ids) + len(missing_ids) > node_limit:
                    truncated_nodes += len(missing_ids)
                    return False
                selected_ids.update(missing_ids)
                selected_edges.append((edge, role))
                seen_edges.add(edge["edge_id"])
                return True

            for edge in self._edges_by_source(conn, [node_id]):
                if _is_hierarchy_edge(edge):
                    add_edge(edge, "parent")

            frontier = [node_id]
            for _ in range(child_depth):
                if not frontier:
                    break
                next_frontier: list[str] = []
                for edge in self._edges_by_target(conn, frontier):
                    if not _is_hierarchy_edge(edge):
                        continue
                    if add_edge(edge, "child") and edge["source_node_id"] not in frontier:
                        next_frontier.append(edge["source_node_id"])
                frontier = sorted(set(next_frontier))

            if include_related:
                incident = self._edges_by_source(conn, [node_id]) + self._edges_by_target(conn, [node_id])
                for edge in sorted(incident, key=lambda item: (item["edge_type"], item["edge_id"])):
                    if not _is_hierarchy_edge(edge):
                        add_edge(edge, "related")

            records.update(self._node_rows_by_id(conn, sorted(selected_ids)))
            degree_map = self._degree_map(conn, sorted(selected_ids))

        nodes = [
            self._node_from_row(
                records[current_id],
                degree_map.get(current_id, 0),
                core_score(
                    records[current_id]["node_type"],
                    degree_map.get(current_id, 0),
                    0,
                    0,
                    float(records[current_id]["confidence"] or 0.0),
                ),
            )
            for current_id in sorted(selected_ids)
        ]
        return VizGraph(
            nodes=nodes,
            edges=[self._edge_from_row(edge, role) for edge, role in selected_edges],
            meta={
                "center_node_id": node_id,
                "child_depth": child_depth,
                "node_limit": node_limit,
                "edge_limit": edge_limit,
                "truncated_nodes": truncated_nodes,
                "truncated_edges": truncated_edges,
                "include_related": include_related,
                "hierarchy_policy": "category_and_explicit_subclass_only",
            },
        )

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _search_rows(
        self, conn: sqlite3.Connection, query: str, match_kind: Literal["exact", "alias", "prefix", "contains"], limit: int
    ) -> list[sqlite3.Row]:
        if match_kind == "exact":
            return conn.execute(
                "SELECT * FROM graph_nodes WHERE normalized_name = ? ORDER BY node_type, node_id LIMIT ?",
                (query, limit),
            ).fetchall()
        if match_kind == "alias":
            return conn.execute(
                """
                SELECT n.* FROM graph_aliases a
                JOIN graph_nodes n ON n.node_id = a.node_id
                WHERE a.normalized_alias = ?
                ORDER BY n.node_type, n.node_id LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        pattern = self._escape_like(query) + ("%" if match_kind == "prefix" else "%")
        return conn.execute(
            "SELECT * FROM graph_nodes WHERE normalized_name LIKE ? ESCAPE '\\' ORDER BY node_type, node_id LIMIT ?",
            (pattern if match_kind == "prefix" else f"%{self._escape_like(query)}%", limit),
        ).fetchall()

    def _alias_prefix_rows(self, conn: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
        return conn.execute(
            """
            SELECT n.* FROM graph_aliases a
            JOIN graph_nodes n ON n.node_id = a.node_id
            WHERE a.normalized_alias LIKE ? ESCAPE '\\'
            ORDER BY n.node_type, n.node_id LIMIT ?
            """,
            (self._escape_like(query) + "%", limit),
        ).fetchall()

    def search(self, query: str, limit: int = MAX_SEARCH_RESULTS) -> list[VizSearchResult]:
        normalized = normalize_name(query)
        if not normalized:
            return []
        limit = self._bounded(limit, MAX_SEARCH_RESULTS)
        with self._connect() as conn:
            results: list[VizSearchResult] = []
            seen: set[str] = set()
            sources = [
                ("exact", self._search_rows(conn, normalized, "exact", limit)),
                ("alias", self._search_rows(conn, normalized, "alias", limit)),
                ("prefix", self._search_rows(conn, normalized, "prefix", limit)),
                ("prefix", self._alias_prefix_rows(conn, normalized, limit)),
                ("contains", self._search_rows(conn, normalized, "contains", limit)),
            ]
            for match_kind, rows in sources:
                for row in rows:
                    if row["node_id"] in seen:
                        continue
                    seen.add(row["node_id"])
                    degree = self._degree_map(conn, [row["node_id"]]).get(row["node_id"], 0)
                    results.append(
                        VizSearchResult(
                            node_id=row["node_id"],
                            label=row["canonical_name"],
                            node_type=row["node_type"],
                            degree=degree,
                            match_kind=match_kind,
                        )
                    )
                    if len(results) == limit:
                        return results
        return results

    def detail(self, node_id: str) -> dict[str, Any]:
        """Return bounded node metadata without evidence text or internal paths."""

        with self._connect() as conn:
            records = self._node_rows_by_id(conn, [node_id])
            if node_id not in records:
                raise KeyError(node_id)
            row = records[node_id]
            aliases = [
                item["alias"]
                for item in conn.execute(
                    "SELECT alias FROM graph_aliases WHERE node_id = ? ORDER BY alias LIMIT 10", (node_id,)
                )
            ]
            edge_rows = self._edges_by_source(conn, [node_id]) + self._edges_by_target(conn, [node_id])
            evidence_rows = conn.execute(
                """
                SELECT DISTINCT e.doc_short, e.page_start, e.page_end
                FROM graph_node_evidence ne
                JOIN graph_evidence e ON e.evidence_id = ne.evidence_id
                WHERE ne.node_id = ?
                ORDER BY e.doc_short, e.page_start
                LIMIT 10
                """,
                (node_id,),
            ).fetchall()
            degree = self._degree_map(conn, [node_id]).get(node_id, 0)
        return {
            "id": row["node_id"],
            "label": row["canonical_name"],
            "node_type": row["node_type"],
            "degree": degree,
            "confidence": float(row["confidence"] or 0.0),
            "aliases": aliases,
            "connection_counts": {
                "hierarchy": sum(1 for edge in edge_rows if _is_hierarchy_edge(edge)),
                "related": sum(1 for edge in edge_rows if not _is_hierarchy_edge(edge)),
            },
            "evidence": [
                {
                    "doc_short": evidence["doc_short"],
                    "page_start": evidence["page_start"],
                    "page_end": evidence["page_end"],
                }
                for evidence in evidence_rows
            ],
        }
