# 162. GraphDB-VectorStore Stable Key Sync Implementation Report

작성일: 2026-06-01
대상 프로젝트: `insurance-rag-chatbot`

## 1. 작업 목적

GraphDB 근거와 VectorStore 청크가 문자열 chunk id에 과하게 의존해 연결되던 구조를 정리했다.
이번 변경의 목표는 다음 두 가지였다.

- GraphDB evidence와 VectorStore가 공통 stable key를 공유하게 만든다.
- 조회 로직과 sync 진단 로직이 같은 lookup 규칙을 사용하게 만든다.

## 2. 핵심 변경

### 2.1 stable key 추가

공통 metadata key로 `source_chunk_id`를 도입했다.

- 기본 인덱스와 `v2_only`는 기존 chunk id를 그대로 `source_chunk_id`로 사용
- `v1_v2_combined`는 `심평원_v1_ch_000001` 같은 id를 `심평원_ch_000001` 형태의 canonical source id로 정규화

관련 파일:

- `src/retrieval/chunk_lookup.py`
- `src/parser/chunker.py`
- `src/parser/ocr_chunker.py`
- `scripts/build_ocr_combined_chunks.py`

### 2.2 VectorStore lookup 규칙 통합

기존에는 `get_by_ids()`가 문자열 fallback만 사용했다.
이제 lookup 순서는 아래와 같다.

1. direct collection id hit
2. legacy 문자열 fallback hit
3. `source_chunk_id` metadata hit

이를 위해 `ChunkLookupRef`와 `get_by_refs()`를 추가했다.

관련 파일:

- `src/retrieval/vector_store.py`

### 2.3 Graph retrieval payload 확장

Graph retriever가 evidence에서 `source_chunk_id`를 읽고,
`source_chunk_refs`를 별도 구조로 전달하도록 바꿨다.

관련 파일:

- `src/graph/retriever.py`
- `src/api/rag_service.py`
- `src/rag/pipeline.py`
- `src/ui/streamlit_app.py`

### 2.4 Graph sync diagnostic 강화

기존 sync 진단은 `direct_hit / fallback_hit / doc_page_hit / missing` 중심이었다.
이제 `source_chunk_hit`을 별도 집계한다.

관련 파일:

- `src/graph/vector_sync.py`
- `scripts/check_graph_vector_sync.py`
- `frontend/js/pages/admin.js`

### 2.5 현재 데이터 백필 스크립트 추가

이미 구축된 JSONL / Chroma / GraphDB에 `source_chunk_id`를 넣기 위한 스크립트를 추가했다.

- `scripts/backfill_chunk_lookup_metadata.py`

주의:

- 초기 버전은 combined chunk와 source chunk 개수 1:1 대응을 가정해 실패했다.
- 실제 데이터는 `v1_v2_combined`의 `v1` 행 수가 `chunks_v1_original_ocr.jsonl`과 정확히 같지 않았다.
- 이를 chunk id 정규화 기반으로 수정했다.
- Chroma `update()` 제약에 맞춰 metadata encoding 및 batch update도 보강했다.

## 3. 검증 결과

### 3.1 테스트

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_vector_store.py tests/test_check_graph_vector_sync.py tests/test_api_admin.py tests/test_api_chat_stream.py tests/test_api_rag_service_payload.py tests/test_graph_retriever.py -q
```

결과:

```text
29 passed, 1 warning
```

전체 회귀:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

결과:

```text
494 passed, 3 warnings
```

### 3.2 sync diagnostic

#### `v1_v2_combined`

```text
hit_rate: 100.00%
direct_hit: 300
source_chunk_hit: 0
doc_page_hit: 0
missing: 0
```

의미:

- GraphDB와 combined 인덱스는 기존 direct chunk id 정합성이 이미 매우 높았다.

#### `v2_only`

```text
hit_rate: 100.00%
direct_hit: 0
source_chunk_hit: 7
doc_page_hit: 293
missing: 0
```

의미:

- stable key 기반 회수가 실제로 일부 활성화되었다.
- 다만 많은 건은 아직 문서/페이지 fallback에 의존한다.

#### `default`

```text
hit_rate: 93.67%
direct_hit: 0
source_chunk_hit: 0
doc_page_hit: 281
missing: 19
```

의미:

- 남은 19개 miss는 구현 결함보다 구조적 차이의 영향이 크다.
- GraphDB는 OCR/combined 기반 evidence를 포함하지만, `default` 인덱스에는 상담사례집/실무가이드 OCR 청크가 직접 존재하지 않는다.

## 4. 현재 결론

이번 작업으로 해결된 부분:

- GraphDB와 VectorStore가 공통 stable key `source_chunk_id`를 사용할 수 있게 됨
- retrieval path와 sync diagnostic이 같은 lookup 규칙을 공유하게 됨
- 기존 데이터에도 backfill 가능 경로를 마련함
- 관리자 진단에서 stable key 회수량을 확인 가능하게 됨

남은 구조적 한계:

- `default` 인덱스는 OCR 문서군이 빠져 있어 일부 miss가 계속 남는다.
- `v2_only`에서도 direct id 정합성보다는 doc/page fallback 비중이 아직 높다.
- 장기적으로는 GraphDB build와 Chroma ingest가 같은 canonical chunk manifest를 직접 공유하는 방식이 더 바람직하다.

## 5. 다음 권장 작업

1. `scripts/check_graph_vector_sync.py` 결과를 관리자 페이지에서 index mode별로 전환 조회 가능하게 만들기
2. GraphDB build 단계에서 `source_chunk_id`를 전역 필수 필드로 강제하기
3. Chroma 재빌드 시 canonical manifest row id를 저장해 `source_chunk_hit`보다 `direct_hit` 비중을 더 높이기
