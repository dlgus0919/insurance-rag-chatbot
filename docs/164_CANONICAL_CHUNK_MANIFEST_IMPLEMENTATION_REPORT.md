# 164. Canonical Chunk Manifest Implementation Report

작성일: 2026-06-01
대상 프로젝트: `insurance-rag-chatbot`
대상 범위: `v2_only / v1_v2_combined / GraphDB` canonical chunk identity 정렬

## 1. 구현 목적

이번 작업의 목적은 `v2_only`, `v1_v2_combined`, `GraphDB`가 같은 근거를 서로 다른 chunk id로 관리하던 구조를 정리하고, 동일 근거를 공통 `canonical_chunk_id`로 참조하도록 재편하는 것이었다.

핵심 목표는 다음과 같다.

- canonical manifest를 기준 데이터로 도입
- `v2_only`, `v1_v2_combined`를 manifest 기반 파생 인덱스로 전환
- GraphDB evidence에 `canonical_chunk_id`를 저장
- sync 진단이 `doc/page fallback`이 아니라 canonical key hit 중심으로 동작하도록 전환

## 2. 주요 변경 사항

### 2.1 canonical manifest 계층 추가

신규 파일:

- `src/retrieval/canonical_manifest.py`
- `scripts/build_canonical_chunk_manifest.py`
- `scripts/build_index_from_canonical_manifest.py`

구현 내용:

- canonical manifest row의 표준 필드를 정의했다.
- `canonical_chunk_id`, `source_variants`, `doc_short`, `page_start`, `page_end`를 기준으로 `v2_only`, `v1_v2_combined`를 파생하도록 했다.
- `v1`과 `v2` chunk 수가 항상 같다고 가정하지 않고, variant availability 중심 구조로 구현했다.

### 2.2 chunk metadata stable key 확장

변경 파일:

- `src/parser/chunker.py`
- `src/parser/ocr_chunker.py`
- `src/retrieval/chunk_lookup.py`
- `src/retrieval/vector_store.py`

구현 내용:

- 기본 chunk/OCR chunk 생성 시 `canonical_chunk_id`, `source_chunk_id`를 metadata에 저장하도록 확장했다.
- VectorStore lookup은 direct id 이후 `canonical_chunk_id`, `source_chunk_id` metadata hit를 지원하도록 변경했다.

### 2.3 GraphDB evidence canonical key 저장

변경 파일:

- `src/graph/schema.py`
- `src/graph/store.py`
- `src/graph/extractors.py`
- `src/graph/retriever.py`
- `src/graph/build.py`
- `scripts/build_graph_index.py`

구현 내용:

- `graph_evidence`에 `canonical_chunk_id` 컬럼을 추가했다.
- extractor가 evidence 생성 시 canonical/source id를 함께 기록하도록 바꿨다.
- retriever와 API payload가 canonical/source refs를 함께 전달하도록 정비했다.
- Graph build는 canonical manifest를 입력으로 받을 수 있게 확장했다.

### 2.4 sync 진단 고도화

변경 파일:

- `src/graph/vector_sync.py`
- `scripts/check_graph_vector_sync.py`
- `frontend/js/pages/admin.js`

구현 내용:

- sync 진단에 `canonical_chunk_hit` 상태를 추가했다.
- 관리자 화면에서 stable key 회수량을 canonical/source 합산 기준으로 보여주도록 조정했다.

### 2.5 backfill 및 이행기 호환

신규/변경 파일:

- `scripts/backfill_chunk_lookup_metadata.py`
- `scripts/build_ocr_combined_chunks.py`

구현 내용:

- 기존 chunk JSONL, Chroma metadata, GraphDB evidence를 대상으로 canonical/source key backfill을 지원한다.
- 기존 fallback 경로는 유지하되, 기본 동작이 canonical key hit 쪽으로 이동하도록 했다.

## 3. 구현 중 확인된 핵심 이슈와 수정

초기 canonical manifest 적용 후 `v2_only`는 다음 상태였다.

- `hit_rate: 100%`
- `direct_hit: 0`
- `canonical_chunk_hit: 7`
- `doc_page_hit: 293`

원인은 `v2_only` OCR 품질 문제가 아니라, canonical manifest 구성 시 다수의 `v2_manual` chunk가 `v1_v2_combined` variant로만 들어가고 `v2_only` variant로 승격되지 않았기 때문이다.

이에 따라 `scripts/build_canonical_chunk_manifest.py`를 수정해:

- combined chunk 중 `v2_manual` 성격을 가진 row를 감지하고
- 해당 row에 `v2_only` variant가 없으면 이를 `v2_only` variant로 승격

하도록 보완했다.

수정 후 `v2_only` 인덱스를 manifest 기반으로 재생성한 결과, sync 진단은 다음과 같이 바뀌었다.

- `hit_rate: 100%`
- `direct_hit: 0`
- `canonical_chunk_hit: 300`
- `doc_page_hit: 0`

즉 `v2_only`가 더 이상 page fallback에 의존하지 않고, canonical identity로 GraphDB evidence를 직접 회수하게 되었다.

## 4. 검증 결과

### 4.1 targeted tests

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_check_graph_vector_sync.py tests/test_api_admin.py tests/test_api_rag_service_payload.py tests/test_graph_retriever.py tests/test_vector_store.py -q
PYTHONPATH=. .venv/bin/pytest tests/test_build_canonical_chunk_manifest.py tests/test_canonical_manifest.py -q
```

결과:

- `25 passed, 1 warning`
- `2 passed`

### 4.2 rebuild / backfill

```bash
PYTHONPATH=. .venv/bin/python scripts/build_canonical_chunk_manifest.py
PYTHONPATH=. .venv/bin/python scripts/build_index_from_canonical_manifest.py --index-mode v2_only
PYTHONPATH=. .venv/bin/python scripts/build_index_from_canonical_manifest.py --index-mode v1_v2_combined
PYTHONPATH=. .venv/bin/python scripts/build_graph_index.py --canonical-manifest data/processed/chunks_canonical_manifest.jsonl --source-mode v1_v2_combined --rebuild
PYTHONPATH=. .venv/bin/python scripts/backfill_chunk_lookup_metadata.py
```

핵심 결과:

- canonical manifest rows: `15,682`
- `v2_only` rebuilt chunks: `15,682`
- `v1_v2_combined` rebuilt chunks: `15,682`

### 4.3 sync diagnostics

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_vector_sync.py --index-mode v2_only --limit 300
PYTHONPATH=. .venv/bin/python scripts/check_graph_vector_sync.py --index-mode v1_v2_combined --limit 300
```

결과:

- `v2_only`
  - `hit_rate: 100.00%`
  - `canonical_chunk_hit: 300`
  - `doc_page_hit: 0`
  - `missing: 0`
- `v1_v2_combined`
  - `hit_rate: 100.00%`
  - `direct_hit: 300`
  - `missing: 0`

### 4.4 full regression

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

결과:

- `496 passed, 3 warnings`

warning은 기존 deprecation warning이며 이번 구현으로 인한 실패는 없었다.

## 5. 결론

이번 작업으로 다음 조건을 충족했다.

- `GraphDB`, `v2_only`, `v1_v2_combined`가 canonical manifest 기반 identity 체계를 공유한다.
- `v2_only`가 `doc/page fallback` 중심 구조에서 벗어나 canonical key 회수 구조로 전환되었다.
- 기존 `v1_v2_combined` direct hit 품질은 유지되었다.
- Graph evidence와 VectorStore sync 진단은 이제 canonical hit 여부를 직접 측정할 수 있다.

남은 범위는 `default` 인덱스의 구조 차이 문제이며, 이는 이번 canonical manifest refactor의 직접 목표 범위에는 포함되지 않는다.
