# 170. Clarification UX State Fix Report

작성일: 2026-06-01
대상: GraphRAG 명확화/되묻기 UX

## 문제

일반 질의의 `추가 확인 필요` 패널에서 다음 문제가 확인되었다.

- 사용자가 이미 선택한 조건을 다음 질의에서 다시 묻는 경우가 있었다.
- 현재 패널에 없는 선택값이 `자주 쓰는 조건` 프리셋으로 합성되어 선택된 것처럼 표시되었다.
- 확인 질문이 명확화 패널과 처리 경고에 중복 노출되었다.

## 원인

- 프론트엔드는 `clarification.selections` payload를 보내고 있었지만, 백엔드 Graph planner는 이를 구조화 상태로 직접 반영하지 않았다.
- 프론트엔드 프리셋은 현재 필요한 명확화 그룹과 무관하게 넓게 노출되었다.
- 프리셋 적용 시 화면에 없는 값을 hidden synthetic selection으로 추가했다.
- `clarification_questions`를 별도 패널에 렌더링하면서 API warning으로도 다시 내보냈다.

## 변경 내용

- `GraphQueryPlanner.plan()`이 `clarification` payload를 받아 `policy_generation`, `visit_type`, `policy_product`, `evidence_tags`, `coverage_topics`, `conditions`, `treatment_purpose`, `term_correction`에 직접 반영하도록 했다.
- `GraphRetriever.retrieve()`와 API `prepare_retrieved_context()`가 clarification payload를 전달하도록 연결했다.
- 이미 선택된 명확화 그룹은 같은 질문을 다시 생성하지 않도록 보정했다.
- 프론트엔드 `자주 쓰는 조건`은 현재 패널에 실제로 선택 가능한 그룹만 포함하는 프리셋으로 제한했다.
- hidden synthetic selection 생성을 제거했다.
- 확인 질문 중복 경고(`CLARIFICATION_RECOMMENDED`)를 제거하고 구조화 payload의 명확화 패널만 사용하도록 했다.

## 검증

```bash
python -m py_compile src/graph/query_planner.py src/graph/retriever.py src/api/rag_service.py src/api/routes/chat.py
node --check frontend/js/pages/chat.js
pytest tests/test_graph_review_path_planner.py tests/test_api_chat_stream.py tests/test_api_rag_service_payload.py -q
```

결과:

- Python compile: 통과
- JS syntax check: 통과
- 관련 pytest: `16 passed, 1 warning`

E2E 참고:

- `npm run test:e2e -- tests/e2e/chat.spec.js`는 현재 DGX workspace에 `node_modules/.bin/playwright`가 없어 실행하지 못했다.
- 대신 E2E spec은 synthetic selection 제거 정책에 맞춰 갱신했다.

## 런타임 반영

`insurance-chat-gptoss` tmux 세션을 재시작해 `127.0.0.1:18080` 앱에 새 코드를 반영했다.

