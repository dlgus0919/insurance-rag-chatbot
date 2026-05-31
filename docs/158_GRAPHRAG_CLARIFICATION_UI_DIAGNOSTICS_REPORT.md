# 158. GraphRAG Clarification UI and Diagnostics Report

작성일: 2026-05-30
대상 단계: `156_GRAPHRAG_NEXT_DEVELOPMENT_PLAN.md`의 P2-P3 후속 UI/API 연결
작업 경로: `/srv/shared/projects/insurance-rag-chatbot`

## 1. 작업 목적

이전 단계에서 `GraphQueryPlanner`가 생성하던 다음 정보를 실제 사용자 화면과 관리자 검색 진단에서 활용 가능하게 연결했다.

- `clarification_questions`
- `normalized_terms`
- `ambiguous_terms`
- `graph_review_paths`

기존에는 planner/API payload에는 값이 있어도 웹앱 일반 질의 응답 카드에서는 확인 질문이 별도 블록으로 표시되지 않았고, 관리자 RAG 검색 진단에도 질의 이해/정규화 정보가 남지 않았다.

## 2. 변경 내용

### 2.1 사용자 채팅 화면

`frontend/js/pages/chat.js`에 다음 렌더링을 추가했다.

- `추가 확인 필요` 블록
  - 모호 조건 tag
  - 추가 확인 질문 목록
  - 입력 용어 정규화 목록
- `구조화 검토 경로` 블록
  - path type label
  - status label
  - summary
  - required evidence
  - review action

`frontend/css/chat.css`에는 다음 스타일을 추가했다.

- `.msg-clarifications`
- `.graph-review-paths`
- `.clarify-tags`
- `.review-status`
- `.review-summary`
- `.review-line`

### 2.2 관리자 RAG 검색 진단

`src/api/routes/chat.py`의 `_build_rag_diagnostics`가 `debug.graph_result.plan`에서 다음 값을 audit detail에 저장하도록 확장했다.

- `normalized_terms`
- `ambiguous_terms`
- `clarification_questions`
- `graph_review_path_count`

`frontend/js/pages/admin.js`는 검색 진단 탭에서 `질의 이해/명확화` 패널을 표시한다.

표시 항목:

- 정규화 용어
- 모호 조건
- 확인 질문
- Graph review path count

## 3. 변경 파일

- `src/api/routes/chat.py`
- `frontend/js/pages/chat.js`
- `frontend/css/chat.css`
- `frontend/js/pages/admin.js`
- `tests/test_api_chat_stream.py`
- `tests/test_api_admin.py`
- `docs/158_GRAPHRAG_CLARIFICATION_UI_DIAGNOSTICS_REPORT.md`

## 4. 검증

### 4.1 JS syntax check

명령:

```bash
node --check frontend/js/pages/chat.js
node --check frontend/js/pages/admin.js
```

결과:

```text
pass
```

### 4.2 관련 pytest

명령:

```bash
PYTHONPATH=. .venv/bin/pytest   tests/test_api_chat_stream.py   tests/test_api_admin.py   tests/test_graph_review_path_planner.py   tests/test_eval_graph_review_paths.py   tests/test_api_rag_service_payload.py -q
```

결과:

```text
16 passed, 1 warning
```

## 5. Self-review

점검 결과:

- 확인 질문은 LLM 답변 텍스트에만 의존하지 않고 구조화 payload에서 별도 표시된다.
- 관리자 검색 진단에도 질의 정규화/모호성 정보가 남아 사후 점검이 가능하다.
- 기존 Graph facts 표시를 제거하지 않고 review path 표시를 추가했다.
- API audit payload가 기존 steps 구조를 유지하므로 기존 진단 UI와 호환된다.

남은 위험:

- 실제 브라우저 렌더링은 dev server를 띄워 시각 확인하는 별도 단계가 필요하다.
- `GraphDB evidence -> VectorStore chunk` 정합성 진단은 아직 P4 후속 작업으로 남아 있다.
- LLM 기반 사용자 입력 보정은 아직 적용하지 않았고, 현재는 문서 기반 alias/rule 정규화가 중심이다.
