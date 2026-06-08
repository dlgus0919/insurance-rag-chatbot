# 191. Structured Evidence Visibility Phase 1 Implementation Report

## Version

- Work version: `v1.0.4-candidate`
- Base: `v1.0.3` 이후 `master`
- Date: 2026-06-08

## Summary

`190_PROJECT_DIRECTION_AND_ONTOLOGY_OPERATING_PLAN.md`의 Phase 1인 **Structured Evidence Visibility Stabilization**을 1차 구현했다.

핵심 목표는 GraphDB direct edge가 없거나 GraphDB 조회가 실패해도, Planner가 구조화 단서를 인식한 질문에서는 프론트가 렌더링 가능한 `graph_review_paths`를 받도록 하는 것이다.

## Implemented Changes

수정 파일:

- `src/graph/retriever.py`
- `src/api/rag_service.py`
- `tests/test_graph_retriever.py`
- `tests/test_api_chat_stream.py`

추가 문서:

- `docs/190_PROJECT_DIRECTION_AND_ONTOLOGY_OPERATING_PLAN.md`
- `docs/191_STRUCTURED_EVIDENCE_VISIBILITY_PHASE1_REPORT.md`

## Behavior

### Before

GraphDB 파일이 없거나, GraphDB 조회 중 예외가 발생하거나, 직접 연결 edge가 없으면 `graph_review_paths`가 비어 프론트의 구조화 검토 섹션이 노출되지 않을 수 있었다.

이 경우 사용자는 일반 RAG 출처만 볼 수 있고, GraphRAG가 판단 조건을 인식했는지 또는 직접 구조화 근거가 없었는지 구분하기 어려웠다.

### After

Planner가 다음 구조화 단서를 인식하면 최소 fallback review path를 생성한다.

- 판단 조건 또는 보장 주제
- 합병증/후유증/부작용 주장
- 진단코드
- 하나의 질병/상해 관련 판단 단서

직접 GraphDB 조항 경로가 없으면 `status="missing"`으로 내려가며, UI에서는 "직접 연결된 조항 없음" 상태를 표시할 수 있다.

GraphDB 조회 예외가 발생한 API 경로에서도 `GraphRetriever.build_fallback_result()`를 통해 renderable graph payload를 생성한다.

## Non-Goals

이번 작업은 하드코딩 로직을 완전히 제거하는 작업이 아니다.

다음 작업은 아직 남아 있다.

- raw 문서 기반 candidate concept/rule extraction
- human approval workflow
- OntologyRegistry v2 상태/출처/승인 schema
- GraphDB rebuild 후 direct edge 생성 품질 개선
- RuleRegistry 분리

## Verification

로컬 Mac:

```bash
pytest tests/test_graph_retriever.py -q
node --test tests/test_frontend_assistant_display.mjs
```

결과:

- `4 passed`
- Node frontend display test `3 passed`

DGX:

```bash
.venv/bin/pytest \
  tests/test_graph_retriever.py \
  tests/test_api_chat_stream.py::test_prepare_retrieved_context_uses_renderable_graph_fallback_on_graph_exception \
  tests/test_api_chat_stream.py::test_prepare_retrieved_context_hides_missing_graph_chunk_warning \
  tests/test_ontology_registry.py \
  tests/test_graph_review_path_planner.py \
  -q

.venv/bin/python scripts/check_ontology_sync.py
.venv/bin/python -m compileall -q src/graph/retriever.py src/api/rag_service.py
node --test tests/test_frontend_assistant_display.mjs
```

결과:

- Pytest: `21 passed, 1 warning`
- Ontology sync: PASS (`concepts=49`, `aliases=109`, `candidate_aliases=18`, `retrieval_rules=4`)
- Compileall: PASS
- Node frontend display test: `3 passed`

DGX live smoke:

```bash
/srv/ai-ops/bin/insurance-rag-up --replace \
  --provider vllm \
  --model gemma-4-31b-it-nvfp4 \
  --skip-prepare \
  --no-llm-switch
```

`/api/chat/stream`에 실제 질의 2건을 전송해 SSE `graph` 이벤트와 최종 답변을 확인했다.

1. `이륜자동차를 타다 사고가 났습니다... 통지하지 않았습니다...`
   - final answer: 1건
   - graph event: 1건
   - `graph_review_paths`: 1건
   - path: `claim_condition_review`
   - status: `missing`
   - summary: `직접 연결된 판단 조건 경로를 찾지 못했습니다.`

2. `N39.3 진단으로 질병급여 실손의료비 청구가 가능한가요?`
   - final answer: 1건
   - graph event: 1건
   - `graph_review_paths`: 3건
   - paths: `diagnosis_review`, `claim_condition_review`, `generation_rule_review`
   - statuses: `confirmed`, `review_required`, `review_required`

참고: Codex in-app Browser는 `127.0.0.1:18080` 조작을 보안 정책으로 차단했다. 따라서 이번 live smoke는 동일 터널을 통한 HTTP SSE 검증과 frontend render unit test 조합으로 수행했다.

## Remaining Risk

fallback path는 "직접 연결된 구조화 근거 없음"을 명확히 보여주는 안정화 장치다.

따라서 이 작업만으로 GraphDB ontology 품질이 좋아지는 것은 아니다. 실제 보험 업무 활용도를 높이려면 다음 단계에서 raw 문서 기반 candidate extraction과 실무자 승인 workflow를 구현해야 한다.
