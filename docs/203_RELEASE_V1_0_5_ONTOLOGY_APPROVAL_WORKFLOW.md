# 203. Release v1.0.5 - Ontology Approval Workflow

## Summary

`v1.0.5`는 온톨로지 실무자 승인 workflow를 DGX 운영 흐름에 편입하는 패치 버전이다.

이번 버전은 다음 두 작업을 함께 포함한다.

- `docs/192_GPT_OSS_120B_LAUNCH_FAILURE_REPORT.md`: `gpt-oss-120b` DGX 단일 장비 기동 실패 원인과 운영 판단 기록
- `docs/201`, `docs/202`: 온톨로지 실무자 승인 workflow 계획 및 Phase 1~3 구현 결과

## Included Changes

### 1. GPT-OSS 120B 상태 명시

`gpt-oss-120b` 모델 파일은 다운로드 완료 상태이나, DGX Spark 단일 장비에서 SGLang 서버 초기화 중 OOM성 SIGKILL로 기동 실패했다.

따라서 현재 운영 앱에서는 `다운로드 완료 / 기동 검증 실패` 상태로 분리하고, 실사용 선택 모델로 취급하지 않는 것이 맞다.

### 2. Ontology practitioner approval workflow

추가된 핵심 구성:

- 후보 저장소: `data/ontology/review/candidates.jsonl`
- 승인 로그: `data/ontology/review/review_log.jsonl`
- 적용 로그: `data/ontology/review/applied_reviews.jsonl`
- active manifest: `data/ontology/concepts.active.json`
- CLI: `scripts/ontology_review.py`
- DGX GUI: `ops/bin/insurance-rag-ontology-review-gui`

실무자는 DGX 바탕화면 실행기를 통해 승인 대기 후보가 있는지 확인하고, 후보별로 승인/보류/거절을 선택할 수 있다.

### 3. Registry active manifest loading

온톨로지 registry는 다음 순서로 manifest를 선택한다.

1. `INSURANCE_ONTOLOGY_MANIFEST`
2. `data/ontology/concepts.active.json`
3. `data/ontology/concepts.json`

운영 manifest를 직접 덮어쓰지 않고 승인된 후보만 active manifest로 병합하므로 rollback이 단순하다.

### 4. Test-only auto approval

테스트 자동 승인은 `test_candidate=true` 후보에만 적용된다.

운영 후보는 LLM/Codex 자동 승인 대상에서 제외된다. 자동 승인 로그는 `reviewer=codex-test-auto`로 남긴다.

## Verification

DGX에서 확인한 검증:

```bash
bash -n ops/bin/insurance-rag-desktop-launcher
bash -n ops/bin/insurance-rag-ontology-review-gui
.venv/bin/python -m py_compile src/ontology/review_store.py src/ontology/manifest_merge.py scripts/ontology_review.py
.venv/bin/python -m pytest tests/test_ontology_review_store.py tests/test_ontology_manifest_merge.py tests/test_ontology_registry.py -q
.venv/bin/python scripts/check_ontology_sync.py
.venv/bin/python -m pytest tests/test_pipeline.py::test_expand_retrieval_query_for_three_major_non_covered_items tests/test_pipeline.py::test_expand_retrieval_query_for_traffic_accident tests/test_pipeline.py::test_expand_retrieval_query_for_motorcycle tests/test_pipeline.py::test_expand_retrieval_query_for_drunk_injury -q
.venv/bin/python -m pytest tests/test_graph_review_path_planner.py tests/test_graph_review_path_retriever.py -q
/srv/ai-ops/bin/insurance-rag-ontology-review-gui --dry-run
```

결과:

- ontology 관련 테스트: `12 passed`
- 검색 확장 회귀 테스트: `4 passed`
- Graph review planner/retriever 테스트: `17 passed`
- ontology sync check: passed
- wrapper syntax check: passed
- GUI dry-run: passed

## Remaining Work

이번 버전은 Phase 1~3 MVP다.

다음 작업은 별도 버전에서 진행한다.

- 관리자 페이지 온톨로지 승인 탭
- 원천 문서 기반 후보 자동 추출 파이프라인
- 승인 후보가 실제 GraphDB에 반영된 뒤 운영 질의에서 어떤 경로로 노출되는지에 대한 end-to-end 검증
