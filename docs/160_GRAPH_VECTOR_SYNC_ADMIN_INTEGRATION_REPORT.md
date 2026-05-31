# 160. GraphDB-VectorStore Sync Admin Integration Report

작성일: 2026-05-31
대상 단계: `156_GRAPHRAG_NEXT_DEVELOPMENT_PLAN.md`의 P4 관리자 연결
작업 경로: `/srv/shared/projects/insurance-rag-chatbot`

## 1. 작업 목적

이전 단계에서 만든 `scripts/check_graph_vector_sync.py`를 관리자 화면에서 확인 가능한 진단 기능으로 연결했다.

이번 변경의 목적은 GraphDB 근거가 실제 Chroma 인덱스에서 회수되는지 운영자가 앱 안에서 바로 확인할 수 있게 하는 것이다.

## 2. 변경 내용

### 2.1 공용 진단 모듈 분리

`src/graph/vector_sync.py`를 추가했다.

포함 기능:

- GraphDB `graph_evidence` row 로딩
- Graph chunk id fallback 후보 생성
- Chroma collection direct/fallback/doc-page hit 검사
- summary와 예시 JSON report 생성

`scripts/check_graph_vector_sync.py`는 이 공용 모듈을 호출하는 CLI wrapper로 정리했다.

### 2.2 Admin API 추가

`GET /api/admin/graph-vector-sync`

query:

- `index_mode`: `default`, `v2_only`, `v1_v2_combined`
- `limit`: 기본 300, 최대 2000
- `seed`: 샘플링 seed

반환:

- `available`
- `index_mode`
- `graph_path`
- `chroma_dir`
- `sampled_evidence_rows`
- `summary.status_counts`
- `summary.hit_rate`
- `summary.by_doc_short`
- `examples`

### 2.3 관리자 UI 연결

관리자 페이지의 `RAG 검색 진단` 탭에 `GraphDB 근거 정합성` 패널을 추가했다.

표시 항목:

- 샘플 근거 수
- 회수율
- 직접 일치 수
- 문서/페이지 fallback 회수 수
- 누락 수
- 문서별 누락 상위

현재 UI는 기본 운영 인덱스 기준 샘플 300건을 조회한다.

## 3. 변경 파일

- `src/graph/vector_sync.py`
- `scripts/check_graph_vector_sync.py`
- `src/api/routes/admin.py`
- `frontend/js/config.js`
- `frontend/js/modules/admin.js`
- `frontend/js/pages/admin.js`
- `tests/test_check_graph_vector_sync.py`
- `tests/test_api_admin.py`
- `docs/160_GRAPH_VECTOR_SYNC_ADMIN_INTEGRATION_REPORT.md`

## 4. 검증 결과

문법 검증:

```bash
.venv/bin/python -m py_compile scripts/check_graph_vector_sync.py src/graph/vector_sync.py
node --check frontend/js/pages/admin.js
node --check frontend/js/modules/admin.js
node --check frontend/js/config.js
```

결과:

```text
pass
```

관련 테스트:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_check_graph_vector_sync.py tests/test_api_admin.py -q
```

결과:

```text
6 passed, 1 warning
```

Graph review path 회귀:

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_graph_review_paths.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_review_paths.jsonl \
  --output reports/graph_review_paths/eval_graph_review_paths_after_admin_sync_20260531.jsonl
```

결과:

```text
Graph review path evaluation: 18/18 passed
```

전체 테스트:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

결과:

```text
489 passed, 3 warnings
```

운영 샘플 확인:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_vector_sync.py \
  --index-mode default \
  --limit 300
```

결과:

```text
sampled: 300
hit_rate: 93.67%
direct_hit: 0
fallback_hit: 0
doc_page_hit: 281
missing: 19
top_missing_docs:
  상담사례집: 13 / 13
  실무가이드: 6 / 6
```

## 5. Self-review

- API는 GraphDB와 Chroma를 수정하지 않는 read-only 진단이다.
- 기본 limit을 300으로 제한해 관리자 탭 진입 시 과도한 부하를 피했다.
- 전체 검사가 필요할 때는 CLI에서 `--limit 0`으로 별도 실행하도록 분리했다.
- UI는 진단 결과를 경고만 숨기지 않고 `direct_hit`, `doc_page_hit`, `missing`으로 분리해 보여준다.

남은 작업:

- 관리자 UI에서 `index_mode`를 선택해 3개 인덱스별 진단을 전환하는 컨트롤 추가
- 진단 결과를 audit log 또는 report 파일로 저장하는 기능
- GraphDB rebuild 시 통합 인덱스 chunk id를 canonical로 둘지, 모드별 evidence id를 둘지 정책 확정
