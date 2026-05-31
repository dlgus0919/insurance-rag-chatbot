# 159. GraphDB-VectorStore Evidence Sync Diagnostic Report

작성일: 2026-05-31
대상 단계: `156_GRAPHRAG_NEXT_DEVELOPMENT_PLAN.md`의 P4 1차 구현
작업 경로: `/srv/shared/projects/insurance-rag-chatbot`

## 1. 작업 목적

GraphDB의 `graph_evidence.chunk_id`가 현재 Chroma VectorStore에서 실제로 조회되는지 수치화하는 진단 도구를 추가했다.

기존 런타임에는 `get_by_ids()` fallback과 `get_by_doc_page()` fallback이 있었지만, 전체 Graph evidence 기준으로 다음을 분리해 보여주는 도구가 없었다.

- `direct_hit`: GraphDB chunk id가 VectorStore에 그대로 존재
- `fallback_hit`: `_v2_manual`, `_v1_original`, `_v1_v2_combined` 등 ID 변형 fallback으로 조회
- `doc_page_hit`: chunk id는 맞지 않지만 문서명/페이지 overlap으로 근거 회수 가능
- `missing`: ID와 문서/페이지 fallback 모두 실패

## 2. 변경 파일

- `scripts/check_graph_vector_sync.py`
- `tests/test_check_graph_vector_sync.py`
- `docs/159_GRAPH_VECTOR_SYNC_DIAGNOSTIC_REPORT.md`

## 3. 사용 방법

기본 인덱스 샘플 진단:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_vector_sync.py \
  --index-mode default \
  --limit 1000 \
  --output-json reports/graph_review_paths/graph_vector_sync_default_sample_20260531.json
```

OCR 보정본 인덱스:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_vector_sync.py \
  --index-mode v2_only \
  --limit 1000 \
  --output-json reports/graph_review_paths/graph_vector_sync_v2_only_sample_20260531.json
```

원본+보정본 통합 인덱스:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_vector_sync.py \
  --index-mode v1_v2_combined \
  --limit 1000 \
  --output-json reports/graph_review_paths/graph_vector_sync_v1_v2_combined_sample_20260531.json
```

필요하면 `--doc-short`, `--source-method`, `--chroma-dir`, `--graph`로 범위를 좁힐 수 있다.

## 4. DGX 샘플 진단 결과

### 4.1 기본 인덱스

```text
sampled: 1000
hit_rate: 94.90%
direct_hit: 0
fallback_hit: 0
doc_page_hit: 949
missing: 51
top_missing_docs:
  상담사례집: 37 / 37
  실무가이드: 14 / 14
```

해석:

- 현재 GraphDB evidence의 chunk id는 기본 인덱스의 실제 Chroma id와 직접 일치하지 않는다.
- 다만 문서명/페이지 fallback으로 대부분 회수된다.
- 기본 인덱스에서 상담사례집/실무가이드 OCR 계열 evidence는 누락이 발생한다. 이 영역은 기본 인덱스보다 OCR 보정본/통합 인덱스가 적합하다.

### 4.2 보정본 OCR 인덱스

```text
sampled: 1000
hit_rate: 100.00%
direct_hit: 0
fallback_hit: 0
doc_page_hit: 1000
missing: 0
```

해석:

- chunk id 직접 일치는 없지만 문서명/페이지 fallback으로 전부 회수된다.
- OCR 보정본 인덱스는 Graph evidence 근거 회수 관점에서 안정적으로 동작한다.

### 4.3 원본+보정본 OCR 통합 인덱스

```text
sampled: 1000
hit_rate: 100.00%
direct_hit: 1000
fallback_hit: 0
doc_page_hit: 0
missing: 0
```

해석:

- 현재 GraphDB evidence chunk id는 통합 인덱스와 가장 직접적으로 정합된다.
- GraphRAG 근거 chunk id를 그대로 회수해야 하는 기능은 통합 인덱스에서 가장 깔끔하게 작동한다.

## 5. 검증

단위 테스트:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_check_graph_vector_sync.py -q
```

결과:

```text
3 passed in 0.08s
```

문법 검증:

```bash
.venv/bin/python -m py_compile scripts/check_graph_vector_sync.py
```

결과:

```text
pass
```

## 6. Self-review

점검 결과:

- 진단은 GraphDB나 Chroma를 수정하지 않는 read-only 스크립트다.
- 직접 hit와 fallback hit, 문서/페이지 fallback을 구분해 기존 경고의 실제 위험도를 수치화한다.
- JSON 산출물을 남기므로 관리자 탭 연동이나 추세 비교로 확장할 수 있다.
- 기본 인덱스에서 OCR 계열 근거가 누락되는 현상이 드러났으므로, 향후 인덱스 라우팅과 관리자 경고에 반영할 수 있다.

남은 작업:

- 관리자 검색 진단 탭에서 이 결과를 직접 실행/표시하는 연결은 아직 하지 않았다.
- 전체 evidence 검사(`--limit 0`)는 샘플보다 오래 걸릴 수 있어 별도 운영 명령으로 분리하는 것이 좋다.
- GraphDB rebuild 시 어떤 인덱스 모드의 chunk id를 canonical로 저장할지 정책을 명확히 해야 한다.
