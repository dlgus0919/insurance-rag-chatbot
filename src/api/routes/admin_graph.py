"""Read-only, bounded GraphDB visualization endpoints for administrators."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, TypeVar

from fastapi import APIRouter, Depends, Path as ApiPath, Query

from src import config
from src.api.deps import require_permission
from src.api.exceptions import AppException
from src.api.schemas.admin_graph import (
    GraphVisualizationDetailResponse,
    GraphVisualizationResponse,
    GraphVisualizationSearchResponse,
)
from src.auth.users import User
from src.graph.visualization import (
    DEFAULT_FOCUS_EDGES,
    DEFAULT_FOCUS_NODES,
    DEFAULT_OVERVIEW_EDGES,
    DEFAULT_OVERVIEW_NODES,
    MAX_CHILD_DEPTH,
    MAX_FOCUS_EDGES,
    MAX_FOCUS_NODES,
    MAX_OVERVIEW_EDGES,
    MAX_OVERVIEW_NODES,
    MAX_SEARCH_RESULTS,
    GraphVisualizationService,
    VizGraph,
)

router = APIRouter(prefix="/admin/graph", tags=["admin-graph"])

_Result = TypeVar("_Result")
_HIERARCHY_POLICY = "category_and_explicit_subclass_only"


def _unavailable() -> AppException:
    return AppException(
        "GRAPH_VISUALIZATION_UNAVAILABLE",
        "GraphDB 시각화 데이터를 사용할 수 없습니다. 관리자에게 그래프 재빌드를 요청하세요.",
        status_code=503,
    )


def _read_failed() -> AppException:
    return AppException(
        "GRAPH_READ_FAILED",
        "GraphDB 시각화 데이터를 읽을 수 없습니다. 관리자에게 상태 점검을 요청하세요.",
        status_code=503,
    )


def _node_not_found() -> AppException:
    return AppException("GRAPH_NODE_NOT_FOUND", "선택한 GraphDB 노드를 찾을 수 없습니다.", status_code=404)


def _read_graph(action: Callable[[GraphVisualizationService], _Result]) -> _Result:
    try:
        return action(GraphVisualizationService(config.GRAPH_INDEX_PATH))
    except FileNotFoundError as exc:
        raise _unavailable() from exc
    except sqlite3.Error as exc:
        raise _read_failed() from exc


def _serialize_graph(graph: VizGraph) -> dict[str, Any]:
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


def _load_overview_snapshot(node_limit: int, edge_limit: int) -> dict[str, Any]:
    snapshot_path = config.GRAPH_VIZ_SNAPSHOT_PATH
    try:
        raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise _unavailable() from exc

    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise _unavailable()
    raw_nodes = raw.get("nodes")
    raw_edges = raw.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise _unavailable()

    nodes: list[dict[str, Any]] = []
    for item in raw_nodes:
        if not isinstance(item, dict):
            continue
        try:
            nodes.append(
                {
                    "id": str(item["id"]),
                    "label": str(item["label"]),
                    "node_type": str(item["node_type"]),
                    "degree": int(item["degree"]),
                    "score": float(item["score"]),
                    "confidence": float(item["confidence"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
        if len(nodes) == node_limit:
            break

    visible_ids = {node["id"] for node in nodes}
    edges: list[dict[str, str]] = []
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        try:
            edge = {
                "id": str(item["id"]),
                "source": str(item["source"]),
                "target": str(item["target"]),
                "edge_type": str(item["edge_type"]),
                "semantic_role": "overview",
            }
        except (KeyError, TypeError, ValueError):
            continue
        if edge["source"] not in visible_ids or edge["target"] not in visible_ids:
            continue
        edges.append(edge)
        if len(edges) == edge_limit:
            break

    raw_meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    graph_manifest = raw.get("graph_manifest") if isinstance(raw.get("graph_manifest"), dict) else {}
    manifest = {
        key: str(graph_manifest[key])
        for key in ("build_date", "source_mode", "node_count", "edge_count")
        if key in graph_manifest
    }
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "node_limit": node_limit,
            "edge_limit": edge_limit,
            "truncated_nodes": max(0, len(raw_nodes) - len(nodes)),
            "truncated_edges": max(0, len(raw_edges) - len(edges)),
            "hierarchy_policy": _HIERARCHY_POLICY,
            "graph_manifest": manifest,
            "snapshot_generated": bool(raw.get("generated_at")),
            "snapshot_hierarchy_policy": raw_meta.get("hierarchy_policy"),
        },
    }


@router.get("/overview", response_model=GraphVisualizationResponse)
async def overview(
    node_limit: int = Query(default=DEFAULT_OVERVIEW_NODES, ge=1, le=MAX_OVERVIEW_NODES),
    edge_limit: int = Query(default=DEFAULT_OVERVIEW_EDGES, ge=1, le=MAX_OVERVIEW_EDGES),
    _: User = Depends(require_permission("admin.stats")),
) -> dict[str, Any]:
    """Return the precomputed, bounded main graph without opening GraphDB."""

    return _load_overview_snapshot(node_limit, edge_limit)


@router.get("/search", response_model=GraphVisualizationSearchResponse)
async def search(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=MAX_SEARCH_RESULTS, ge=1, le=MAX_SEARCH_RESULTS),
    _: User = Depends(require_permission("admin.stats")),
) -> dict[str, Any]:
    """Search canonical node names and aliases through read-only SQLite indexes."""

    items = _read_graph(lambda service: service.search(q, limit))
    return {
        "items": [
            {
                "id": item.node_id,
                "label": item.label,
                "node_type": item.node_type,
                "degree": item.degree,
                "match_kind": item.match_kind,
            }
            for item in items
        ],
        "total": len(items),
    }


@router.get("/nodes/{node_id}/neighborhood", response_model=GraphVisualizationResponse)
async def node_neighborhood(
    node_id: str = ApiPath(min_length=1, max_length=200),
    child_depth: int = Query(default=1, ge=1, le=MAX_CHILD_DEPTH),
    node_limit: int = Query(default=DEFAULT_FOCUS_NODES, ge=1, le=MAX_FOCUS_NODES),
    edge_limit: int = Query(default=DEFAULT_FOCUS_EDGES, ge=1, le=MAX_FOCUS_EDGES),
    include_related: bool = Query(default=False),
    _: User = Depends(require_permission("admin.stats")),
) -> dict[str, Any]:
    """Return only the selected node's bounded, read-only neighborhood."""

    try:
        graph = _read_graph(
            lambda service: service.neighborhood(
                node_id,
                child_depth=child_depth,
                node_limit=node_limit,
                edge_limit=edge_limit,
                include_related=include_related,
            )
        )
    except KeyError as exc:
        raise _node_not_found() from exc
    return _serialize_graph(graph)


@router.get("/nodes/{node_id}", response_model=GraphVisualizationDetailResponse)
async def node_detail(
    node_id: str = ApiPath(min_length=1, max_length=200),
    _: User = Depends(require_permission("admin.stats")),
) -> dict[str, Any]:
    """Return a small node summary and source reference metadata only."""

    try:
        return _read_graph(lambda service: service.detail(node_id))
    except KeyError as exc:
        raise _node_not_found() from exc
