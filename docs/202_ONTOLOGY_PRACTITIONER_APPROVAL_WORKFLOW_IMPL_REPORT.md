# 202. Ontology Practitioner Approval Workflow Implementation Report

## Summary

`docs/201_ONTOLOGY_PRACTITIONER_APPROVAL_WORKFLOW_PLAN.md`의 Phase 1~3 범위에 맞춰 온톨로지 실무자 승인 workflow MVP를 구현했다.

이번 구현은 운영 온톨로지 manifest를 직접 덮어쓰지 않고, 승인 후보를 별도 저장소에서 관리한 뒤 승인된 후보만 `data/ontology/concepts.active.json`으로 병합한다. DGX 바탕화면 실행기는 LLM 선택 전에 승인 대기 후보를 감지하고, `zenity` 기반 승인 UI를 통해 실무자가 승인/보류/거절을 선택할 수 있다.

## Implemented

### 1. 후보 저장소 및 승인 로그

추가 파일:

- `src/ontology/review_store.py`
- `tests/test_ontology_review_store.py`

저장 경로:

- `data/ontology/review/candidates.jsonl`
- `data/ontology/review/review_log.jsonl`
- `data/ontology/review/applied_reviews.jsonl`

지원 상태:

- `pending`
- `approved`
- `held`
- `rejected`
- `applied`

테스트 자동 승인은 `test_candidate=true` 후보만 대상으로 하며, reviewer는 `codex-test-auto`로 기록한다.

### 2. Active manifest 생성

추가 파일:

- `src/ontology/manifest_merge.py`
- `tests/test_ontology_manifest_merge.py`

동작:

- base manifest: `data/ontology/concepts.json`
- active manifest: `data/ontology/concepts.active.json`
- 승인 또는 적용 완료 후보만 active manifest에 병합
- `concept_id` 중복과 alias 충돌 시 적용 중단
- 기존 active manifest는 `data/ontology/backups/`에 백업

### 3. Registry active manifest 로딩

수정 파일:

- `src/ontology/registry.py`
- `src/ontology/__init__.py`
- `tests/test_ontology_registry.py`

로딩 우선순위:

1. `INSURANCE_ONTOLOGY_MANIFEST`
2. `data/ontology/concepts.active.json`
3. `data/ontology/concepts.json`

### 4. CLI

추가 파일:

- `scripts/ontology_review.py`

주요 명령:

```bash
python scripts/ontology_review.py --pending-count
python scripts/ontology_review.py --summary
python scripts/ontology_review.py --list-json --status pending
python scripts/ontology_review.py --decide <candidate_id> --decision approve
python scripts/ontology_review.py --auto-approve-test
python scripts/ontology_review.py --apply --rebuild-graph
python scripts/ontology_review.py --seed-test-candidate
```

`--apply --rebuild-graph`는 active manifest 검증 후 GraphDB를 재구축한다. 재구축 전 기존 GraphDB는 `data/index/graph/backups/`에 백업한다.

### 5. DGX 바탕화면 실행기 연동

수정 파일:

- `ops/bin/insurance-rag-desktop-launcher`
- `ops/bin/insurance-rag-prepare`

추가 파일:

- `ops/bin/insurance-rag-ontology-review-gui`

동작:

1. 바탕화면 아이콘 실행
2. 실행기가 승인 대기 후보 수 확인
3. 승인 대기 후보가 있으면 `insurance-rag-ontology-review-gui` 실행
4. 실무자가 후보별 승인/보류/거절 선택
5. 승인 후보가 있으면 active manifest 생성 및 GraphDB 재구축
6. 기존 LLM 선택 및 앱 기동 흐름으로 복귀

DGX 설치본도 동기화했다.

- `/srv/ai-ops/bin/insurance-rag-desktop-launcher`
- `/srv/ai-ops/bin/insurance-rag-ontology-review-gui`

## Guardrails

- 운영 후보는 LLM 자동 승인 대상이 아니다.
- `test_candidate=true` 후보만 테스트 자동 승인 가능하다.
- `held`와 `rejected` 후보는 active manifest에 병합하지 않는다.
- active manifest 검증 실패 시 GraphDB rebuild를 진행하지 않는다.
- alias 충돌 또는 concept id 중복은 적용 단계에서 실패 처리한다.

## Verification

DGX에서 실행:

```bash
bash -n ops/bin/insurance-rag-desktop-launcher
bash -n ops/bin/insurance-rag-ontology-review-gui
.venv/bin/python -m py_compile src/ontology/review_store.py src/ontology/manifest_merge.py scripts/ontology_review.py
.venv/bin/python -m pytest tests/test_ontology_review_store.py tests/test_ontology_manifest_merge.py tests/test_ontology_registry.py -q
.venv/bin/python scripts/ontology_review.py --pending-count
.venv/bin/python scripts/ontology_review.py --auto-approve-test --dry-run
.venv/bin/python scripts/ontology_review.py --seed-test-candidate --dry-run
/srv/ai-ops/bin/insurance-rag-ontology-review-gui --dry-run
.venv/bin/python scripts/check_ontology_sync.py
.venv/bin/python -m pytest tests/test_pipeline.py::test_expand_retrieval_query_for_three_major_non_covered_items tests/test_pipeline.py::test_expand_retrieval_query_for_traffic_accident tests/test_pipeline.py::test_expand_retrieval_query_for_motorcycle tests/test_pipeline.py::test_expand_retrieval_query_for_drunk_injury -q
.venv/bin/python -m pytest tests/test_graph_review_path_planner.py tests/test_graph_review_path_retriever.py -q
```

결과:

- ontology 관련 테스트: `12 passed`
- 검색 확장 회귀 테스트: `4 passed`
- Graph review planner/retriever 테스트: `17 passed`
- ontology sync check: passed
- 설치본 wrapper `bash -n`: passed
- GUI dry-run: pending 후보 0건 기준 정상 종료

## Notes

이번 MVP는 Phase 1~3 범위만 구현했다. 관리자 페이지의 온톨로지 승인 탭과 원천 문서 기반 후보 자동 추출기는 Phase 4~5 범위로 남겨둔다.

운영 후보가 아직 없으면 바탕화면 실행기는 승인 UI를 띄우지 않고 기존 LLM 선택 흐름으로 바로 진행한다.
