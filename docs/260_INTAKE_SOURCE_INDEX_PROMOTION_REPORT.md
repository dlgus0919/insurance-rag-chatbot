# 260. Intake Source Index Promotion 구현 보고서

## 목적

관리자 페이지에서 신규 디지털 PDF 문서를 추가하고, 실무자가 생성 후보를 승인한 뒤 `승인 항목 반영`을 실행하면 다음 자산이 함께 갱신되도록 했다.

- 온톨로지 active manifest
- 보험금 계산 active rule manifest
- 신규 문서 원문 active source overlay
- BM25/Chroma 검색 인덱스
- GraphDB

이 변경은 000번 원칙의 “지식 하드코딩 금지”를 유지하기 위해 신규 문서 본문을 코드 상수나 canonical manifest에 직접 삽입하지 않고, 승인된 intake source overlay로 분리해 빌드 시 병합하는 방식으로 구현했다.

## 핵심 설계

### 1. Active source overlay

`src/ingest/source_promotion.py`를 추가했다.

- 저장 위치: `data/intake/active_sources/`
- chunk 저장: `chunks.jsonl`
- 승격 manifest: `manifest.jsonl`
- 승격 단위: intake job
- idempotency 기준: `job_id`

승인된 온톨로지/룰 후보에서 `intake_job_id`, `staging_chunks_path`, `source_filename`을 수집하고, 승인된 job의 staging chunks를 active source chunks로 승격한다.

각 promoted chunk에는 다음 provenance metadata를 추가한다.

- `intake_job_id`
- `source_filename`
- `source_status=active_intake_source`
- `source_method=admin_digital_pdf_text_layer`
- `canonical_chunk_id`
- `source_chunk_id`

부분 반영 위험을 줄이기 위해 `validate_staging_source_refs()`가 batch 전체를 먼저 검증한 뒤 append가 진행되도록 했다.

### 2. 검색 인덱스 빌더 연결

`scripts/build_index_from_canonical_manifest.py`에 `--active-source-chunks` 옵션과 `build_index_from_manifest()` 함수를 추가했다.

기존 canonical manifest 기반 청크를 만든 뒤 active source overlay가 있으면 뒤에 병합하고, 기존 `build_index()`로 BM25/Chroma를 재빌드한다.

### 3. GraphDB 빌더 연결

`src/graph/build.py`와 `scripts/build_graph_index.py`에 active source chunks 옵션을 추가했다.

GraphDB build 시 canonical manifest가 있으면 canonical chunks에 active source chunks를 병합해 임시 chunks 파일을 만들고, extractor 입력으로 사용한다. canonical manifest가 없고 기존 chunks 파일만 있을 때도 active source overlay를 병합하는 fallback을 둔다.

### 4. 승인 적용 파이프라인 연결

`src/ingest/knowledge_apply.py`의 적용 순서를 다음처럼 확장했다.

1. 온톨로지 dry-run preflight
2. 룰 dry-run preflight
3. 승인된 intake source ref 수집
4. source ref batch 검증 및 active source 승격
5. 온톨로지 실제 적용
6. 룰 실제 적용
7. `v2_only`, `v1_v2_combined` 검색 인덱스 재빌드
8. GraphDB 재빌드

적용 결과에는 `sources`, `index_rebuilt`, `graph_rebuilt`를 포함한다.

### 5. 관리자 UI

관리자 페이지의 승인 반영 확인 문구를 실제 동작에 맞게 수정했다.

- 문서 원문 검색 인덱스(BM25/Chroma)와 GraphDB 재빌드를 명시
- API 반환값이 `completed`가 아니거나 `index_rebuilt/graph_rebuilt`가 false이면 성공 toast를 띄우지 않고 실패로 표시

## 검증 결과

로컬에서 다음 검증을 수행했다.

```bash
python -m pytest tests/test_source_promotion.py tests/test_build_index_from_canonical_manifest_active_sources.py tests/test_graph_build_active_sources.py tests/test_knowledge_apply.py tests/test_intake_runner.py tests/test_file_intake_planner.py -q
```

결과: `24 passed`

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

결과: `10 passed`

```bash
python -m py_compile scripts/build_index_from_canonical_manifest.py scripts/build_graph_index.py src/ingest/source_promotion.py src/ingest/knowledge_apply.py
```

결과: 통과

로컬 전체 API 포함 테스트 묶음은 현재 Mac 작업공간에 `.venv`가 없고 `/opt/anaconda3/bin/python`에 `fastapi`가 설치되어 있지 않아 `tests/test_api_admin_knowledge.py` import 단계에서 중단됐다. DGX `.venv`에서 API 포함 검증을 별도로 수행해야 한다.

DGX 메인 저장소(`/srv/shared/projects/insurance-rag-chatbot`)에는 동일 패치를 반영하고 다음 검증을 수행했다.

```bash
.venv/bin/python -m pytest tests/test_source_promotion.py tests/test_build_index_from_canonical_manifest_active_sources.py tests/test_graph_build_active_sources.py tests/test_knowledge_apply.py tests/test_intake_runner.py tests/test_api_admin_knowledge.py tests/test_file_intake_planner.py -q
```

결과: `30 passed, 1 warning`

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

결과: `10 passed`

```bash
.venv/bin/python -m py_compile scripts/build_index_from_canonical_manifest.py scripts/build_graph_index.py src/ingest/source_promotion.py src/ingest/knowledge_apply.py
```

결과: 통과

실제 BM25/Chroma 운영 인덱스 재빌드 smoke는 산출물 변경과 리소스 사용이 발생하므로 이번 검증에서는 실행하지 않았다. 해당 경로는 단위 테스트에서 `build_index()`를 monkeypatch해 active source overlay 병합 입력을 검증했다.

## 남은 위험

- source overlay append와 이후 ontology/rule/index/graph 재빌드 사이에 장애가 발생하면 자산 간 일시적 불일치가 생길 수 있다. 현재는 관리자 적용 결과와 감사 로그로 확인하는 운영 절차를 전제로 한다.
- 동시 apply 실행에 대한 파일 lock은 아직 없다. 관리자 단일 작업 흐름을 전제로 하며, 다중 운영자가 동시에 apply하는 운영으로 확장할 때 lock 또는 job queue가 필요하다.
- 실제 DGX active DB 재빌드는 embedding/index 비용이 있으므로, 운영 데이터 적용 전에는 DGX `.venv` 기준 테스트와 dry-run 적용 결과를 확인해야 한다.
