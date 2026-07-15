"""Pydantic contracts for the bounded administrator GraphDB visualization."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class GraphVisualizationNode(BaseModel):
    id: str
    label: str
    node_type: str
    degree: int
    score: float
    confidence: float


class GraphVisualizationEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str
    semantic_role: Literal["parent", "child", "related", "overview"]


class GraphVisualizationResponse(BaseModel):
    nodes: list[GraphVisualizationNode]
    edges: list[GraphVisualizationEdge]
    meta: dict


class GraphVisualizationSearchResult(BaseModel):
    id: str
    label: str
    node_type: str
    degree: int
    match_kind: Literal["exact", "alias", "prefix", "contains"]


class GraphVisualizationSearchResponse(BaseModel):
    items: list[GraphVisualizationSearchResult]
    total: int


class GraphVisualizationEvidence(BaseModel):
    doc_short: str
    page_start: int | None = None
    page_end: int | None = None


class GraphVisualizationDetailResponse(BaseModel):
    id: str
    label: str
    node_type: str
    degree: int
    confidence: float
    aliases: list[str]
    connection_counts: dict[str, int]
    evidence: list[GraphVisualizationEvidence]
