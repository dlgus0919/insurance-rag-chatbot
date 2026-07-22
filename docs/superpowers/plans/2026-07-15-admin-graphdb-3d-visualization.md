# Admin GraphDB 3D Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자 페이지에서 핵심 GraphDB 구조를 저부하 3D 그래프로 보고, 검색 또는 노드 선택으로 상위 1단계와 제한된 하위 트리를 탐색하게 한다.

**Architecture:** GraphDB 전체를 브라우저나 API 요청 시점에 스캔하지 않는다. 빌드 단계에서 핵심 노드 스냅숏을 생성하고, 검색·집중 보기는 SQLite 인덱스를 사용하는 관리자 전용 읽기 API로 제한된 부분 그래프만 조회한다. 프런트엔드는 `3d-force-graph`를 별도 번들로 고정하고, 짧은 물리 계산과 카메라 전환 후 렌더링을 정지하며 WebGL 실패 시 2D 트리로 대체한다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, pytest, vanilla JavaScript ES modules, esbuild, `3d-force-graph@1.80.0`, `three@0.185.1`, Node test runner, Playwright, Chrome/Chromium WebGL

## Global Constraints

- GraphDB와 근거 데이터는 읽기 전용으로 유지하며 시각화 화면에서 수정 기능을 제공하지 않는다.
- 전체 그래프를 API 응답 또는 브라우저로 전송하지 않는다.
- 외부 CDN 런타임 의존을 금지하고 정확한 npm 버전과 생성 번들을 저장소 배포 자산으로 고정한다.
- 관리자 권한 검사는 기존 `admin.stats` 권한을 재사용한다.
- 메인 그래프 기본값은 노드 120개, 관계 240개이고 서버 절대 상한은 노드 150개, 관계 300개이다.
- 집중 그래프 기본값은 노드 180개, 관계 360개이고 서버 절대 상한은 노드 250개, 관계 500개이다.
- 검색 결과 절대 상한은 20개, 하위 깊이 절대 상한은 3이다.
- 상위·하위 의미는 명시된 관계 정책으로만 판단하고 등록되지 않은 관계는 `related`로 분류한다.
- GraphDB 탭 이탈 시 요청, 물리 계산, 애니메이션 루프와 이벤트 리스너를 정리한다.
- 사용자 승인 없이 커밋하거나 원격 push하지 않는다. 각 Task 마지막은 검토 체크포인트이다.
- 기존 작업 트리에 다수 변경이 있으므로 시작 전과 종료 전 `git status --short` 및 대상 diff를 확인한다.

---

## File Structure

- Create: `src/graph/visualization.py` - 관계 정책, 핵심 점수, 검색과 부분 그래프 조회
- Create: `scripts/profile_graph_visualization.py` - 노드·관계 분포와 계층 정책 증거 생성
- Create: `scripts/build_graph_visualization_snapshot.py` - 메인 구조 스냅숏 생성
- Modify: `scripts/build_graph_index.py` - GraphDB 빌드 성공 후 스냅숏 생성 연결
- Modify: `src/config.py` - 스냅숏 경로 설정
- Create: `src/api/schemas/admin_graph.py` - GraphDB 시각화 API 계약
- Create: `src/api/routes/admin_graph.py` - 관리자 읽기 API
- Modify: `src/api/main.py` - 라우터 등록
- Create: `frontend/js/modules/admin-graph.js` - Graph API 호출과 응답 정규화
- Create: `frontend/js/graph/force-graph-entry.js` - npm 라이브러리 번들 진입점
- Create: `frontend/js/graph/renderer-3d.js` - 3D 렌더러 수명 주기
- Create: `frontend/js/pages/admin-graph.js` - 검색, 집중 보기, 상세 패널, 2D 대체
- Modify: `frontend/html/admin.html` - GraphDB 탭과 컨테이너
- Modify: `frontend/css/admin.css` - 3D 화면·패널·대체 트리 스타일
- Modify: `frontend/js/pages/admin.js` - GraphDB 탭 수명 주기 연결만 수행
- Modify: `frontend/js/config.js` - API endpoint 추가
- Modify: `frontend/index.html` - 자체 호스팅 Graph 번들 로드
- Modify: `frontend/package.json`, `frontend/package-lock.json` - 버전 고정과 build script
- Create: `frontend/dist/graph-viz.min.js` - 오프라인 실행용 생성 번들
- Create: `tests/test_graph_visualization.py` - 점수, 정책, 검색과 제한 테스트
- Create: `tests/test_api_admin_graph.py` - API 계약, 권한과 오류 테스트
- Create: `tests/test_admin_graph_frontend.mjs` - 프런트엔드 상태·정리·fallback 테스트
- Create: `tests/e2e/admin-graph.spec.js` - 관리자 탐색 흐름
- Create: `docs/268_ADMIN_GRAPHDB_3D_VISUALIZATION_REPORT.md` - 구현 및 DGX 검증 보고서

## Task 1: Profile the real GraphDB and lock the semantic hierarchy policy

**Files:**
- Create: `scripts/profile_graph_visualization.py`
- Create: `tests/test_graph_visualization.py`
- Create: `reports/graph_visualization_profile.json` only during validation; do not commit raw node names by default

**Interfaces:**
- Produces: `profile_graph(db_path: Path, sample_limit: int = 5) -> dict[str, object]`
- Produces: node type counts, edge type counts, type-pair counts, degree percentiles, component summary and redacted samples

- [ ] **Step 1: Inspect the current worktree and actual DGX path contract**

Run:

```bash
git status --short
rg -n "GRAPH_INDEX_PATH|insurance_graph.sqlite|graph_nodes|graph_edges" src/config.py scripts/build_graph_index.py docs/263_DGX_DEMO_REHEARSAL_REPORT.md docs/264_DGX_DEMO_SCENARIO_GUIDE.md
```

Expected: local configured path and DGX documented path are identified without changing files.

- [ ] **Step 2: Write the failing profiler test**

Create `tests/test_graph_visualization.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.profile_graph_visualization import profile_graph


def make_graph(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE graph_nodes (node_id TEXT PRIMARY KEY, node_type TEXT, canonical_name TEXT, normalized_name TEXT, properties_json TEXT, confidence REAL, created_by TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE graph_aliases (alias_id TEXT PRIMARY KEY, node_id TEXT, alias TEXT, normalized_alias TEXT, source TEXT, confidence REAL)")
        conn.execute("CREATE TABLE graph_edges (edge_id TEXT PRIMARY KEY, source_node_id TEXT, target_node_id TEXT, edge_type TEXT, properties_json TEXT, confidence REAL, source_evidence_id TEXT, created_by TEXT, updated_at TEXT)")
        conn.executemany(
            "INSERT INTO graph_nodes VALUES (?, ?, ?, ?, '{}', 1.0, 'test', '')",
            [
                ("root", "ClaimCondition", "청구 조건", "청구 조건"),
                ("decision", "DecisionConcept", "지급 결정", "지급 결정"),
                ("evidence", "EvidenceRequirement", "필요 근거", "필요 근거"),
            ],
        )
        conn.executemany(
            "INSERT INTO graph_edges VALUES (?, ?, ?, ?, '{}', 1.0, NULL, 'test', '')",
            [
                ("e1", "root", "decision", "HAS_DECISION"),
                ("e2", "decision", "evidence", "REQUIRES_EVIDENCE"),
            ],
        )


def test_profile_graph_reports_types_pairs_and_degree(tmp_path: Path) -> None:
    path = tmp_path / "graph.sqlite"
    make_graph(path)
    result = profile_graph(path, sample_limit=2)
    assert result["node_type_counts"] == {
        "ClaimCondition": 1,
        "DecisionConcept": 1,
        "EvidenceRequirement": 1,
    }
    assert result["edge_type_counts"] == {"HAS_DECISION": 1, "REQUIRES_EVIDENCE": 1}
    assert result["max_degree"] == 2
    assert result["edge_type_pairs"]["HAS_DECISION"] == {
        "ClaimCondition->DecisionConcept": 1
    }
```

- [ ] **Step 3: Run the test to verify it fails**

Run:

```bash
pytest -q tests/test_graph_visualization.py::test_profile_graph_reports_types_pairs_and_degree
```

Expected: FAIL because the profiler module does not exist.

- [ ] **Step 4: Implement the read-only profiler**

Create `scripts/profile_graph_visualization.py` with:

```python
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


def profile_graph(db_path: Path, sample_limit: int = 5) -> dict[str, Any]:
    if not db_path.is_file():
        raise FileNotFoundError(f"GraphDB file not found: {db_path}")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        node_type_counts = dict(conn.execute(
            "SELECT node_type, COUNT(*) count FROM graph_nodes GROUP BY node_type ORDER BY node_type"
        ).fetchall())
        edge_type_counts = dict(conn.execute(
            "SELECT edge_type, COUNT(*) count FROM graph_edges GROUP BY edge_type ORDER BY edge_type"
        ).fetchall())
        pair_rows = conn.execute(
            """
            SELECT e.edge_type, s.node_type source_type, t.node_type target_type, COUNT(*) count
            FROM graph_edges e
            JOIN graph_nodes s ON s.node_id = e.source_node_id
            JOIN graph_nodes t ON t.node_id = e.target_node_id
            GROUP BY e.edge_type, s.node_type, t.node_type
            ORDER BY e.edge_type, count DESC, source_type, target_type
            """
        ).fetchall()
        degree_rows = conn.execute(
            """
            WITH endpoints AS (
              SELECT source_node_id node_id FROM graph_edges
              UNION ALL
              SELECT target_node_id node_id FROM graph_edges
            )
            SELECT node_id, COUNT(*) degree FROM endpoints GROUP BY node_id ORDER BY degree DESC, node_id
            """
        ).fetchall()
    pairs: dict[str, dict[str, int]] = {}
    for row in pair_rows:
        pairs.setdefault(row["edge_type"], {})[
            f'{row["source_type"]}->{row["target_type"]}'
        ] = row["count"]
    degrees = [row["degree"] for row in degree_rows]
    return {
        "node_type_counts": node_type_counts,
        "edge_type_counts": edge_type_counts,
        "edge_type_pairs": pairs,
        "max_degree": max(degrees, default=0),
        "connected_node_count": len(degrees),
        "top_degree_node_ids": [row["node_id"] for row in degree_rows[:sample_limit]],
    }
```

Add a CLI that accepts `--db`, `--output`, `--sample-limit`, writes UTF-8 JSON, and defaults to printing redacted aggregate data to stdout. Raw canonical names must not be written unless an explicit `--include-names` flag is passed.

- [ ] **Step 5: Run the unit test and local profile**

Run:

```bash
pytest -q tests/test_graph_visualization.py::test_profile_graph_reports_types_pairs_and_degree
python scripts/profile_graph_visualization.py --db data/index/graph/insurance_graph.sqlite --output reports/graph_visualization_profile.json
```

Expected: test PASS. If the local GraphDB is absent, the second command must fail with the explicit missing-file error and DGX profiling becomes a required execution checkpoint.

- [ ] **Step 6: Profile the DGX GraphDB with the LLM server unchanged**

Run the same script on the DGX workspace using the configured GraphDB path. Do not stop, restart or modify the LLM server for this step. Record only aggregate counts and redacted node IDs in the implementation report.

Expected evidence:

```text
node type counts
edge type counts
source-type -> target-type counts per edge type
maximum and top degree distribution
connected versus isolated node count
five redacted examples for each proposed hierarchy edge
```

- [ ] **Step 7: Lock the hierarchy policy**

Use this conservative initial policy in `src/graph/visualization.py`; change it only if the DGX examples prove a direction is wrong and record that evidence in the report:

```python
HIERARCHY_EDGE_DIRECTIONS: dict[str, tuple[str, str]] = {
    "HAS_TOPIC": ("source", "target"),
    "HAS_DECISION": ("source", "target"),
    "REQUIRES_EVIDENCE": ("source", "target"),
    "HAS_GRADE": ("source", "target"),
    "HAS_CATEGORY": ("source", "target"),
    "HAS_BENEFIT_LIMIT": ("source", "target"),
    "HAS_DEDUCTIBLE_RULE": ("source", "target"),
    "REQUIRES_DOCUMENT": ("source", "target"),
    "HAS_COORDINATION_RULE": ("source", "target"),
    "HAS_GENERATION_RULE": ("source", "target"),
    "DEFINES_CLAIM_UNIT": ("source", "target"),
    "HAS_GROUPING_RULE": ("source", "target"),
    "HAS_RELATION_CRITERION": ("source", "target"),
}
```

All other edge types are `related`, not parent or child.

- [ ] **Step 8: Review checkpoint**

Run:

```bash
git diff --check -- scripts/profile_graph_visualization.py tests/test_graph_visualization.py
git status --short -- scripts/profile_graph_visualization.py tests/test_graph_visualization.py reports/graph_visualization_profile.json
```

Do not commit the profile JSON if it contains node names or operational paths. Do not stage or commit without explicit approval.

## Task 2: Implement deterministic core selection and bounded neighborhood queries

**Files:**
- Create: `src/graph/visualization.py`
- Create: `scripts/build_graph_visualization_snapshot.py`
- Modify: `scripts/build_graph_index.py`
- Modify: `src/config.py`
- Modify: `tests/test_graph_visualization.py`

**Interfaces:**
- Produces: `GraphVisualizationService.overview(node_limit: int, edge_limit: int) -> VizGraph`
- Produces: `GraphVisualizationService.search(query: str, limit: int) -> list[VizSearchResult]`
- Produces: `GraphVisualizationService.neighborhood(node_id: str, child_depth: int, node_limit: int, edge_limit: int, include_related: bool) -> VizGraph`
- Produces: `build_snapshot(db_path: Path, output_path: Path, node_limit: int = 150, edge_limit: int = 300) -> dict[str, object]`

- [ ] **Step 1: Add failing selection and bounds tests**

Append tests that assert:

```python
from src.graph.visualization import GraphVisualizationService


def test_overview_prefers_semantic_root_and_hub_nodes(tmp_path: Path) -> None:
    path = tmp_path / "graph.sqlite"
    make_graph(path)
    service = GraphVisualizationService(path)
    graph = service.overview(node_limit=2, edge_limit=1)
    assert [node.node_id for node in graph.nodes] == ["root", "decision"]
    assert len(graph.edges) == 1
    assert graph.meta["truncated_nodes"] == 1


def test_neighborhood_returns_one_parent_level_and_bounded_children(tmp_path: Path) -> None:
    path = tmp_path / "graph.sqlite"
    make_graph(path)
    service = GraphVisualizationService(path)
    graph = service.neighborhood(
        "decision", child_depth=2, node_limit=10, edge_limit=10, include_related=False
    )
    assert {node.node_id for node in graph.nodes} == {"root", "decision", "evidence"}
    assert {edge.semantic_role for edge in graph.edges} == {"parent", "child"}


def test_search_prefers_exact_name_then_alias(tmp_path: Path) -> None:
    path = tmp_path / "graph.sqlite"
    make_graph(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO graph_aliases VALUES ('a1', 'decision', '결정', '결정', 'test', 1.0)")
    service = GraphVisualizationService(path)
    assert service.search("지급 결정", 20)[0].node_id == "decision"
    assert service.search("결정", 20)[0].node_id == "decision"
```

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
pytest -q tests/test_graph_visualization.py -k "overview or neighborhood or search"
```

Expected: FAIL because the service is not implemented.

- [ ] **Step 3: Implement typed graph DTOs and limits**

In `src/graph/visualization.py`, define:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

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
```

Use `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)` in the service. Enforce limits in the service even if the caller already validated them.

- [ ] **Step 4: Implement core scoring and deterministic selection**

Use this score formula:

```python
SEMANTIC_TYPE_WEIGHT = {
    "DecisionConcept": 8.0,
    "CoverageItem": 8.0,
    "ClaimCondition": 7.0,
    "PolicyBenefitRule": 7.0,
    "EvidenceRequirement": 6.0,
    "DeductibleRule": 6.0,
    "ClaimUnitConcept": 6.0,
    "DiseaseGroupingRule": 5.0,
    "Document": 3.0,
}


def core_score(node_type: str, degree: int, parent_count: int, child_count: int, confidence: float) -> float:
    root_bonus = 4.0 if parent_count == 0 and child_count > 0 else 0.0
    hub_bonus = min(12.0, degree ** 0.5)
    return round(SEMANTIC_TYPE_WEIGHT.get(node_type, 1.0) + root_bonus + hub_bonus + confidence, 6)
```

Sort by `score DESC, degree DESC, node_type ASC, node_id ASC`. Apply a per-type cap of `max(3, node_limit // 5)` before filling unused capacity from the global remainder. Select only edges whose endpoints are selected, sorted by hierarchy first, then edge type and edge ID.

- [ ] **Step 5: Implement bounded parent, child, and related traversal**

Use breadth-first traversal for children, exactly one query layer per depth, stop immediately when node or edge limit is reached, and always include the selected node. Parent traversal is one layer only. Related edges are fetched only when `include_related=True` and consume the same global limits.

Return these meta keys:

```python
{
    "center_node_id": node_id,
    "child_depth": child_depth,
    "node_limit": node_limit,
    "edge_limit": edge_limit,
    "truncated_nodes": truncated_nodes,
    "truncated_edges": truncated_edges,
    "include_related": include_related,
}
```

- [ ] **Step 6: Implement search with existing and new indexes**

Search exact normalized name, exact alias, prefix name, prefix alias, contains name in that order. Escape `%` and `_` in user input. Add these indexes in the graph build schema if absent:

```sql
CREATE INDEX IF NOT EXISTS idx_graph_nodes_normalized_name ON graph_nodes(normalized_name);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_node_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_node_id, edge_type);
```

- [ ] **Step 7: Implement and connect the overview snapshot builder**

Add `GRAPH_VIZ_SNAPSHOT_PATH` in `src/config.py` next to `GRAPH_INDEX_PATH`, defaulting to `data/index/graph/insurance_graph_viz.json`.

`build_graph_visualization_snapshot.py` must write to a sibling temporary file, `fsync`, then use `Path.replace()` for atomic promotion. The JSON must contain:

```json
{
  "schema_version": 1,
  "graph_manifest": {},
  "generated_at": "ISO-8601 UTC",
  "nodes": [],
  "edges": [],
  "meta": {"node_limit": 150, "edge_limit": 300}
}
```

Call the snapshot builder from `scripts/build_graph_index.py` only after the GraphDB build and manifest write complete. If snapshot generation fails, fail the build rather than silently leaving a stale snapshot.

- [ ] **Step 8: Run tests and snapshot smoke**

Run:

```bash
pytest -q tests/test_graph_visualization.py
python -m compileall -q src/graph/visualization.py scripts/profile_graph_visualization.py scripts/build_graph_visualization_snapshot.py
python scripts/build_graph_visualization_snapshot.py --graph data/index/graph/insurance_graph.sqlite --output /tmp/insurance_graph_viz.json
```

Expected: tests PASS, compile PASS, and smoke creates valid JSON when the local GraphDB exists. If absent locally, run the snapshot smoke on DGX.

- [ ] **Step 9: Review checkpoint**

Run `git diff --check` on Task 2 files. Do not stage or commit without explicit approval.

## Task 3: Expose administrator-only graph visualization APIs

**Files:**
- Create: `src/api/schemas/admin_graph.py`
- Create: `src/api/routes/admin_graph.py`
- Modify: `src/api/main.py`
- Create: `tests/test_api_admin_graph.py`

**Interfaces:**
- `GET /api/admin/graph/overview`
- `GET /api/admin/graph/search?q=<text>&limit=20`
- `GET /api/admin/graph/nodes/{node_id}/neighborhood`
- `GET /api/admin/graph/nodes/{node_id}`

- [ ] **Step 1: Write failing API contract tests**

Use a temporary SQLite fixture and dependency overrides. Assert:

```python
def test_graph_overview_requires_admin(client, user_headers):
    assert client.get("/api/admin/graph/overview", headers=user_headers).status_code == 403


def test_graph_overview_returns_bounded_contract(admin_client):
    response = admin_client.get("/api/admin/graph/overview?node_limit=120&edge_limit=240")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"nodes", "edges", "meta"}
    assert len(payload["nodes"]) <= 120
    assert len(payload["edges"]) <= 240


def test_graph_neighborhood_rejects_excessive_limits(admin_client):
    response = admin_client.get(
        "/api/admin/graph/nodes/decision/neighborhood?node_limit=251"
    )
    assert response.status_code == 422


def test_graph_missing_file_does_not_expose_internal_path(admin_client, monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.routes.admin_graph.config.GRAPH_INDEX_PATH", tmp_path / "missing.sqlite")
    response = admin_client.get("/api/admin/graph/search?q=결정")
    assert response.status_code == 503
    assert str(tmp_path) not in response.text
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest -q tests/test_api_admin_graph.py
```

Expected: FAIL because schemas and routes do not exist.

- [ ] **Step 3: Implement Pydantic response schemas**

Define exact schema names:

```python
class AdminGraphNode(BaseModel):
    id: str
    label: str
    node_type: str
    degree: int = Field(ge=0)
    score: float
    confidence: float


class AdminGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str
    semantic_role: Literal["parent", "child", "related", "overview"]


class AdminGraphPayload(BaseModel):
    nodes: list[AdminGraphNode]
    edges: list[AdminGraphEdge]
    meta: dict[str, Any]


class AdminGraphSearchItem(BaseModel):
    id: str
    label: str
    node_type: str
    degree: int
    match_kind: Literal["exact", "alias", "prefix", "contains"]


class AdminGraphSearchResponse(BaseModel):
    items: list[AdminGraphSearchItem]
    total: int
```

- [ ] **Step 4: Implement the route and error mapping**

Create router prefix `/admin/graph`, tag `admin-graph`, and use `Depends(require_permission("admin.stats"))` on every endpoint. Map:

```text
missing GraphDB or snapshot -> 503 GRAPH_UNAVAILABLE
SQLite read error -> 503 GRAPH_READ_FAILED
unknown node -> 404 GRAPH_NODE_NOT_FOUND
empty search query -> 422 INVALID_INPUT
invalid limit or depth -> FastAPI 422
```

Never include `GRAPH_INDEX_PATH` or snapshot absolute path in response messages.

- [ ] **Step 5: Register the router and run tests**

Modify `src/api/main.py` imports and add:

```python
app.include_router(admin_graph.router, prefix="/api")
```

Run:

```bash
pytest -q tests/test_api_admin_graph.py tests/test_api_admin.py
python -m compileall -q src/api/schemas/admin_graph.py src/api/routes/admin_graph.py src/api/main.py
```

Expected: all focused tests PASS.

- [ ] **Step 6: Review checkpoint**

Run `git diff --check` on Task 3 files and inspect that only admin permissions can call the new APIs. Do not commit without explicit approval.

## Task 4: Build the offline 3D renderer with bounded resource use

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`
- Create: `frontend/js/graph/force-graph-entry.js`
- Create: `frontend/js/graph/renderer-3d.js`
- Create: `frontend/dist/graph-viz.min.js`
- Modify: `frontend/index.html`
- Create: `tests/test_admin_graph_frontend.mjs`

**Interfaces:**
- Produces: `createGraphRenderer(container, options) -> rendererController`
- Controller methods: `setGraph`, `focusNode`, `pause`, `resume`, `dispose`

- [ ] **Step 1: Write failing renderer lifecycle tests**

Create Node tests around a fake graph factory:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';

import { createGraphRenderer } from '../frontend/js/graph/renderer-3d.js';

test('renderer pauses after the configured cooldown', () => {
  const calls = [];
  const graph = makeFakeGraph(calls);
  const controller = createGraphRenderer({}, { graphFactory: () => graph, cooldownMs: 1200 });
  controller.setGraph({ nodes: [], edges: [] });
  assert.ok(calls.includes('cooldownTime:1200'));
});

test('renderer disposal stops animation and removes resources', () => {
  const calls = [];
  const graph = makeFakeGraph(calls);
  const controller = createGraphRenderer({}, { graphFactory: () => graph });
  controller.dispose();
  assert.ok(calls.includes('pauseAnimation'));
  assert.ok(calls.includes('destructor'));
});
```

The fake must implement the chainable methods invoked by the controller and record calls.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
node --test tests/test_admin_graph_frontend.mjs
```

Expected: FAIL because renderer module does not exist.

- [ ] **Step 3: Pin and bundle the graph dependencies**

Run from `frontend/` with a writable temporary cache:

```bash
npm_config_cache=/tmp/codex-npm-cache npm install --save-exact 3d-force-graph@1.80.0 three@0.185.1
```

Add package scripts:

```json
"build:graph": "esbuild js/graph/force-graph-entry.js --bundle --minify --outfile=dist/graph-viz.min.js --format=iife",
"build": "npm run build:graph && esbuild js/app.js --bundle --minify --outfile=dist/app.min.js --format=esm"
```

Create `force-graph-entry.js`:

```javascript
import ForceGraph3D from '3d-force-graph';

window.InsuranceGraph3D = ForceGraph3D;
```

Run `npm run build:graph` and ensure `frontend/dist/graph-viz.min.js` exists.

- [ ] **Step 4: Load the self-hosted bundle**

Add before the main module script in `frontend/index.html`:

```html
<script src="/dist/graph-viz.min.js?v=20260715_graphdb_3d" defer></script>
```

Do not add CDN URLs.

- [ ] **Step 5: Implement the bounded renderer controller**

Use these exact defaults in `renderer-3d.js`:

```javascript
const DEFAULTS = Object.freeze({
  cooldownMs: 1200,
  pixelRatioCap: 1.25,
  cameraDurationMs: 650,
  backgroundColor: '#081426',
});

export function createGraphRenderer(container, options = {}) {
  const config = { ...DEFAULTS, ...options };
  const graphFactory = options.graphFactory || globalThis.InsuranceGraph3D;
  if (!graphFactory) throw new Error('GRAPH_RENDERER_UNAVAILABLE');
  const graph = graphFactory()(container)
    .backgroundColor(config.backgroundColor)
    .nodeId('id')
    .nodeLabel((node) => `${node.label} · ${node.node_type}`)
    .nodeAutoColorBy('node_type')
    .nodeVal((node) => Math.min(12, 2 + Math.sqrt(node.degree || 0)))
    .linkSource('source')
    .linkTarget('target')
    .linkOpacity(0.28)
    .linkWidth((edge) => edge.semantic_role === 'overview' ? 1.2 : 1.8)
    .cooldownTime(config.cooldownMs)
    .warmupTicks(30)
    .enableNodeDrag(false);
  graph.renderer().setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, config.pixelRatioCap));

  let disposed = false;
  return {
    setGraph(payload) {
      if (disposed) return;
      graph.graphData({ nodes: payload.nodes, links: payload.edges });
      window.setTimeout(() => { if (!disposed) graph.pauseAnimation(); }, config.cooldownMs + 50);
    },
    focusNode(node) {
      if (disposed || !node) return;
      const distance = 90;
      const ratio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
      graph.resumeAnimation();
      graph.cameraPosition(
        { x: (node.x || 0) * ratio, y: (node.y || 0) * ratio, z: (node.z || 0) * ratio },
        node,
        config.cameraDurationMs,
      );
      globalThis.setTimeout(
        () => { if (!disposed) graph.pauseAnimation(); },
        config.cameraDurationMs + 50,
      );
    },
    onNodeClick(handler) { graph.onNodeClick(handler); },
    pause() { graph.pauseAnimation(); },
    resume() { if (!disposed) graph.resumeAnimation(); },
    dispose() {
      if (disposed) return;
      disposed = true;
      graph.onNodeClick(null);
      graph.pauseAnimation();
      graph._destructor?.();
      container.replaceChildren();
    },
  };
}
```

Do not add directional particles, shadows, post-processing, per-node HTML labels or automatic rotation.

- [ ] **Step 6: Run frontend tests and build checks**

Run:

```bash
node --test tests/test_admin_graph_frontend.mjs
node --check frontend/js/graph/renderer-3d.js
cd frontend && npm run build:graph
```

Expected: tests PASS, syntax PASS, bundle succeeds.

- [ ] **Step 7: Review checkpoint**

Confirm no CDN URL appears:

```bash
rg -n "https://|cdn\." frontend/index.html frontend/js/graph frontend/dist/graph-viz.min.js
```

Expected: no runtime CDN reference in source files. Do not commit without explicit approval.

## Task 5: Integrate search, focus animation, details, and 2D fallback into admin

**Files:**
- Create: `frontend/js/modules/admin-graph.js`
- Create: `frontend/js/pages/admin-graph.js`
- Modify: `frontend/js/config.js`
- Modify: `frontend/js/pages/admin.js`
- Modify: `frontend/html/admin.html`
- Modify: `frontend/css/admin.css`
- Modify: `tests/test_admin_graph_frontend.mjs`
- Create: `tests/e2e/admin-graph.spec.js`

**Interfaces:**
- Produces: `initAdminGraphPage()`, `activateAdminGraphPage()`, `deactivateAdminGraphPage()`, `disposeAdminGraphPage()`
- Consumes: Task 3 APIs and Task 4 renderer controller

- [ ] **Step 1: Add API endpoint constants and helpers**

In `frontend/js/config.js` add:

```javascript
ADMIN_GRAPH_OVERVIEW: '/admin/graph/overview',
ADMIN_GRAPH_SEARCH: '/admin/graph/search',
ADMIN_GRAPH_NODE_BASE: '/admin/graph/nodes',
```

In `admin-graph.js`, export:

```javascript
export function fetchGraphOverview(options = {})
export function searchGraphNodes(query, options = {})
export function fetchGraphNeighborhood(nodeId, options = {})
export function fetchGraphNodeDetail(nodeId)
export function normalizeGraphPayload(payload)
```

Use `encodeURIComponent` for query and node ID, and fixed client defaults matching the server defaults.

- [ ] **Step 2: Write failing page-state tests**

Add tests for:

```javascript
test('graph payload normalization rejects edges with missing endpoints', () => {});
test('selecting a node focuses it before loading its neighborhood', async () => {});
test('deactivation aborts pending requests and pauses rendering', () => {});
test('WebGL failure renders the two-dimensional hierarchy fallback', () => {});
test('labels are escaped before insertion into detail HTML', () => {});
```

Run `node --test tests/test_admin_graph_frontend.mjs` and confirm failure.

- [ ] **Step 3: Add the dedicated admin tab markup**

Add one sidebar item with `data-admin-sub="graph"` and one section `id="sub-graph"`. The section contains:

```html
<div class="graph-toolbar">
  <label class="sr-only" for="admin-graph-search">GraphDB 노드 검색</label>
  <input id="admin-graph-search" type="search" autocomplete="off" placeholder="개념 또는 별칭 검색">
  <button type="button" data-admin-graph-action="search">검색</button>
  <button type="button" data-admin-graph-action="reset">메인 구조로 돌아가기</button>
  <label><input type="checkbox" id="admin-graph-related"> 일반 연관 관계</label>
</div>
<div id="admin-graph-status" role="status" aria-live="polite"></div>
<div class="admin-graph-layout">
  <div id="admin-graph-canvas" aria-label="GraphDB 3D 탐색 화면"></div>
  <aside id="admin-graph-detail" aria-label="선택 노드 상세"></aside>
</div>
<div id="admin-graph-fallback" hidden></div>
```

- [ ] **Step 4: Implement the page lifecycle**

Behavior must be exact:

```text
first activation -> fetch overview -> initialize renderer -> set graph
search submit -> fetch <=20 results -> show keyboard-selectable list
result or node click -> focus current node -> fetch neighborhood -> replace graph -> update detail
reset -> fetch or reuse current-version overview -> set graph -> clear detail
related toggle -> reload current neighborhood with include_related
deactivate -> AbortController.abort + renderer.pause
dispose -> abort + renderer.dispose + remove bound listeners
WebGL/init error -> hide canvas + show semantic 2D parent/child tree
```

Use `escapeHTML` for every server-provided label and type inserted as HTML.

- [ ] **Step 5: Connect the tab without growing admin.js responsibilities**

Import the four page lifecycle functions. In `showSub`, add title `graph: 'GraphDB 탐색'`, call `activateAdminGraphPage()` only for graph, and call `deactivateAdminGraphPage()` when any other subpage becomes active. On admin page teardown, call `disposeAdminGraphPage()`.

- [ ] **Step 6: Add bounded responsive styling**

Use a canvas height of `clamp(420px, 64vh, 760px)`, a 320px detail column on wide screens, and a single-column layout under 1100px. Do not use CSS filters or animated backgrounds. Ensure the 2D fallback is usable with keyboard and screen readers.

- [ ] **Step 7: Add Playwright flow**

Mock the four Graph APIs with small deterministic fixtures. Verify admin access, overview, search, click, camera callback proxy, detail update, reset, fallback and no duplicate event on repeated tab entry.

- [ ] **Step 8: Run focused frontend verification**

Run:

```bash
node --test tests/test_admin_graph_frontend.mjs tests/test_admin_knowledge_frontend.mjs
find frontend/js -name '*.js' -print0 | xargs -0 -n1 node --check
npx playwright test tests/e2e/admin-graph.spec.js
```

Expected: all focused checks PASS.

- [ ] **Step 9: Review checkpoint**

Inspect only Task 5 diffs, confirm existing admin tabs still load, and do not stage or commit without explicit approval.

## Task 6: Validate DGX Spark coexistence with the live LLM and document results

**Files:**
- Create: `docs/268_ADMIN_GRAPHDB_3D_VISUALIZATION_REPORT.md`
- Modify only if measurements require: Graph limits and renderer constants in their owning files

**Interfaces:**
- Consumes: completed feature, current DGX LLM launch configuration and real GraphDB
- Produces: reproducible performance table and final safe limits

- [ ] **Step 1: Run local full verification before DGX deployment**

Run:

```bash
pytest -q tests/test_graph_visualization.py tests/test_api_admin_graph.py tests/test_api_admin.py
node --test tests/test_admin_graph_frontend.mjs tests/test_admin_knowledge_frontend.mjs
cd frontend && npm run build
git diff --check
```

Expected: all checks PASS.

- [ ] **Step 2: Capture the DGX baseline without changing the LLM server**

Record:

```text
DGX OS and browser version
active LLM model and serving backend
GraphDB build manifest and node/edge totals
screen resolution and browser zoom
DGX Dashboard CPU/GPU/system memory readings
available memory and swap
same fixed prompt first-token and total latency for at least 5 runs
```

Do not rely on aggregate `nvidia-smi` memory usage alone on the integrated GPU.

- [ ] **Step 3: Measure the six required coexistence states**

Measure the same prompt and system metrics for:

```text
1. LLM server only
2. admin page open, GraphDB tab unopened
3. overview graph displayed
4. maximum focus graph displayed
5. camera transition while LLM inference runs
6. graph settled while five sequential LLM requests run
```

Collect browser Performance traces for states 3 through 5 and confirm the renderer stops after cooldown in state 6.

- [ ] **Step 4: Apply the acceptance gates**

Required:

```text
overview first display <= 2.0 seconds
focus graph display <= 1.0 second after API response
camera transition >= 30 FPS
LLM first-token p50 degradation <= 10 percent versus baseline
no sustained swap growth
no browser crash or WebGL context loss after 30 repeated focus/reset cycles
no LLM OOM
no continuous animation after graph settles
```

If a gate fails, reduce in this order and rerun all states:

```text
1. pixelRatioCap 1.25 -> 1.0
2. overview 120/240 -> 90/180
3. focus 180/360 -> 140/280
4. hover labels -> selected-node label only
5. cooldown 1200ms -> 700ms and warmupTicks 30 -> 15
```

Do not add GPU scheduling, LLM model changes or server restarts to solve a visualization regression without separate user approval.

- [ ] **Step 5: Write the implementation and measurement report**

Create `docs/268_ADMIN_GRAPHDB_3D_VISUALIZATION_REPORT.md` with:

```markdown
# 관리자 GraphDB 3D 시각화 구현 및 DGX 검증 보고서

## 1. 구현 범위
## 2. 변경 파일
## 3. 실제 GraphDB 분포와 계층 정책
## 4. API 및 렌더링 상한
## 5. 개발 PC 검증
## 6. DGX Spark LLM 동시 실행 검증
## 7. 성능 측정 결과
## 8. 실행한 명령과 결과
## 9. 남은 위험
```

Do not include credentials, raw user queries, absolute private paths or unredacted node names from sensitive sources.

- [ ] **Step 6: Run the final regression suite**

Run:

```bash
pytest -q
node --test tests/test_admin_graph_frontend.mjs tests/test_admin_knowledge_frontend.mjs
npx playwright test tests/e2e/admin-graph.spec.js tests/e2e/chat.spec.js
cd frontend && npm run build
git diff --check
git status --short
```

Expected: all available checks PASS. If full pytest contains an unrelated pre-existing failure, preserve the exact failure and prove focused Graph tests pass; do not skip or delete the test.

- [ ] **Step 7: Final self-inspection**

Confirm:

```text
[ ] no full GraphDB payload is exposed
[ ] graph APIs require admin permission
[ ] hierarchy uses the evidence-backed allowlist
[ ] overview and focus limits are enforced server-side
[ ] renderer pauses and disposes correctly
[ ] WebGL fallback is usable
[ ] LLM coexistence gates passed on DGX Spark
[ ] no credentials, raw user data or internal paths appear in report/API
[ ] unrelated user changes remain intact
[ ] no commit or push occurred without explicit approval
```

- [ ] **Step 8: Developer chat delivery checkpoint**

The Developer chat must report changed files, focused and full test results, exact final node/edge limits, DGX measurement table, unrun checks and remaining risks. It must stop before staging, committing or pushing unless the user explicitly authorizes those actions.
