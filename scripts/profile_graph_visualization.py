#!/usr/bin/env python3
"""Profile GraphDB aggregates for the administrator visualization policy."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, math.ceil((len(values) - 1) * ratio) - 1))
    return values[index]


def _component_summary(conn: sqlite3.Connection, total_nodes: int) -> dict[str, Any]:
    parents: dict[str, str] = {}

    def find(node_id: str) -> str:
        parents.setdefault(node_id, node_id)
        while parents[node_id] != node_id:
            parents[node_id] = parents[parents[node_id]]
            node_id = parents[node_id]
        return node_id

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for source, target in conn.execute(
        "SELECT source_node_id, target_node_id FROM graph_edges"
    ):
        union(source, target)

    component_sizes = Counter(find(node_id) for node_id in parents)
    sizes = sorted(component_sizes.values(), reverse=True)
    return {
        "nonisolated_count": len(sizes),
        "nonisolated_nodes": len(parents),
        "isolated_nodes": max(0, total_nodes - len(parents)),
        "largest_sizes": sizes[:10],
    }


def profile_graph(db_path: Path, sample_limit: int = 5) -> dict[str, Any]:
    """Return a redacted, read-only GraphDB profile without node names or IDs."""

    if not db_path.is_file():
        raise FileNotFoundError(f"GraphDB file not found: {db_path}")
    if sample_limit < 1:
        raise ValueError("sample_limit must be at least 1")

    db_uri = f"file:{db_path.resolve()}?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        node_type_counts = dict(
            conn.execute(
                "SELECT node_type, COUNT(*) AS count FROM graph_nodes GROUP BY node_type ORDER BY node_type"
            ).fetchall()
        )
        edge_type_counts = dict(
            conn.execute(
                "SELECT edge_type, COUNT(*) AS count FROM graph_edges GROUP BY edge_type ORDER BY edge_type"
            ).fetchall()
        )
        pair_rows = conn.execute(
            """
            SELECT e.edge_type, s.node_type AS source_type, t.node_type AS target_type,
                   COUNT(*) AS count
            FROM graph_edges e
            JOIN graph_nodes s ON s.node_id = e.source_node_id
            JOIN graph_nodes t ON t.node_id = e.target_node_id
            GROUP BY e.edge_type, s.node_type, t.node_type
            ORDER BY e.edge_type, count DESC, source_type, target_type
            """
        ).fetchall()
        degree_rows = conn.execute(
            """
            SELECT COALESCE(degree_count, 0) AS degree
            FROM graph_nodes n
            LEFT JOIN (
                SELECT node_id, COUNT(*) AS degree_count
                FROM (
                    SELECT source_node_id AS node_id FROM graph_edges
                    UNION ALL
                    SELECT target_node_id AS node_id FROM graph_edges
                ) endpoints
                GROUP BY node_id
            ) d ON d.node_id = n.node_id
            ORDER BY degree
            """
        ).fetchall()
        relationship_counts: Counter[str] = Counter()
        hierarchy_samples: list[dict[str, str]] = []
        for row in conn.execute(
            """
            SELECT e.edge_type, e.properties_json, s.node_type AS source_type,
                   t.node_type AS target_type
            FROM graph_edges e
            JOIN graph_nodes s ON s.node_id = e.source_node_id
            JOIN graph_nodes t ON t.node_id = e.target_node_id
            WHERE e.properties_json IS NOT NULL
            """
        ):
            try:
                relationship = json.loads(row["properties_json"]).get("relationship")
            except (TypeError, json.JSONDecodeError):
                relationship = None
            if not relationship:
                continue
            relationship_counts[f"{row['edge_type']}:{relationship}"] += 1
            if relationship == "subclass_of" and len(hierarchy_samples) < sample_limit:
                hierarchy_samples.append(
                    {
                        "edge_type": row["edge_type"],
                        "source_type": row["source_type"],
                        "target_type": row["target_type"],
                        "relationship": relationship,
                    }
                )

        pairs: dict[str, dict[str, int]] = {}
        for row in pair_rows:
            pairs.setdefault(row["edge_type"], {})[
                f"{row['source_type']}->{row['target_type']}"
            ] = row["count"]
        degrees = [row["degree"] for row in degree_rows]
        total_nodes = sum(node_type_counts.values())
        return {
            "node_count": total_nodes,
            "edge_count": sum(edge_type_counts.values()),
            "node_type_counts": node_type_counts,
            "edge_type_counts": edge_type_counts,
            "edge_type_pairs": pairs,
            "relationship_property_counts": dict(sorted(relationship_counts.items())),
            "hierarchy_samples": hierarchy_samples,
            "degree": {
                "p50": _percentile(degrees, 0.50),
                "p90": _percentile(degrees, 0.90),
                "p99": _percentile(degrees, 0.99),
                "max": max(degrees, default=0),
                "isolated_nodes": degrees.count(0),
            },
            "components": _component_summary(conn, total_nodes),
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write a redacted aggregate GraphDB visualization profile."
    )
    parser.add_argument("--db", type=Path, required=True, help="Read-only GraphDB SQLite file.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    parser.add_argument("--sample-limit", type=int, default=5)
    args = parser.parse_args()

    result = profile_graph(args.db, sample_limit=args.sample_limit)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
