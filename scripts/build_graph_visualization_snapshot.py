#!/usr/bin/env python3
"""Build the bounded public GraphDB visualization snapshot atomically."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.graph.visualization import MAX_OVERVIEW_EDGES, MAX_OVERVIEW_NODES, GraphVisualizationService


def _manifest_summary(db_path: Path) -> dict[str, str]:
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "graph_build_manifest" not in tables:
            return {}
        rows = conn.execute(
            """
            SELECT key, value FROM graph_build_manifest
            WHERE key IN ('build_date', 'source_mode', 'node_count', 'edge_count')
            ORDER BY key
            """
        ).fetchall()
    return {str(key): str(value) for key, value in rows}


def _serialize_graph(graph: Any) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": node.node_id,
                "label": node.label,
                "node_type": node.node_type,
                "degree": node.degree,
                "score": node.score,
                "confidence": node.confidence,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "id": edge.edge_id,
                "source": edge.source,
                "target": edge.target,
                "edge_type": edge.edge_type,
                "semantic_role": edge.semantic_role,
            }
            for edge in graph.edges
        ],
        "meta": graph.meta,
    }


def build_snapshot(
    db_path: Path,
    output_path: Path,
    node_limit: int = MAX_OVERVIEW_NODES,
    edge_limit: int = MAX_OVERVIEW_EDGES,
) -> dict[str, Any]:
    """Write a bounded overview snapshot using an atomic sibling replacement."""

    service = GraphVisualizationService(db_path)
    graph = service.overview(node_limit=node_limit, edge_limit=edge_limit)
    payload = {
        "schema_version": 1,
        "graph_manifest": _manifest_summary(db_path),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **_serialize_graph(graph),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build bounded GraphDB visualization snapshot.")
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node-limit", type=int, default=MAX_OVERVIEW_NODES)
    parser.add_argument("--edge-limit", type=int, default=MAX_OVERVIEW_EDGES)
    args = parser.parse_args()
    payload = build_snapshot(args.graph, args.output, args.node_limit, args.edge_limit)
    print(
        json.dumps(
            {"nodes": len(payload["nodes"]), "edges": len(payload["edges"]), "schema_version": 1},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
