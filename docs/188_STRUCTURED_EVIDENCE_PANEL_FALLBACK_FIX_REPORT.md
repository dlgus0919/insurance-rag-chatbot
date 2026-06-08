# 188. Structured Evidence Panel Fallback Fix Report

## 목적

일반 질의 완료 후 모델이 직접 생성한 구조화 리뷰 템플릿과 Graph payload 기반 패널 렌더링 사이의 계약 불일치를 수정했다. 이번 수정은 `v1.0.3` 패치 릴리스 대상이다.

## 문제

일부 모델은 답변 본문에 `■ 섹션 1️⃣`, `【확정 근거】` 같은 구조화 리뷰 템플릿을 직접 생성한다. 기존 후처리는 이 템플릿을 항상 제거했지만, 동시에 `graph_result.graph_review_paths`, `facts`, `clarification_questions` 등이 비어 있으면 프론트에서 대체 구조화 패널도 렌더링되지 않았다. 그 결과 최종 화면에서 근거 파트가 사라질 수 있었다.

## 변경 사항

- `src/api/rag_service.py`
  - `graph_payload_has_renderable_evidence()`를 추가했다.
  - 렌더 가능한 Graph payload가 있을 때만 embedded review template을 제거한다.
  - Graph payload가 없거나 비어 있으면 모델이 생성한 구조화 본문은 유지하고 trailing source line만 제거한다.
- `src/api/routes/chat.py`
  - `finalize_answer_for_question()`에 실제 `graph_payload`를 전달한다.
- `src/api/routes/sessions.py`
  - 세션 복원과 export에서도 `assistant_meta.graph_result` 기준으로 같은 정규화 규칙을 적용한다.
- `frontend/js/pages/chat.js`
  - `hasRenderableGraphPayload()`를 추가하고 최종 렌더/히스토리 복원 모두 같은 규칙을 사용한다.
  - 렌더 가능한 Graph payload가 있을 때만 모델 생성 구조화 템플릿을 제거한다.
- `frontend/js/config.js`
  - 앱 버전 표기를 `1.0.3`으로 갱신했다.

## 검증

실행한 검증:

```bash
.venv/bin/pytest tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py -q
node --test tests/test_frontend_assistant_display.mjs tests/test_frontend_model_selection_sync.mjs tests/test_frontend_claim_result_compaction.mjs
/srv/ai-ops/bin/insurance-rag-up --replace --provider ollama --model llama-3.3-70b-instruct-q4-k-m
/srv/ai-ops/bin/insurance-rag-status
curl http://127.0.0.1:18080/api/system/models
curl http://127.0.0.1:18080/api/chat/stream
```

결과:

- Python 지정 테스트: `35 passed, 1 warning`
- Node 지정 테스트: `7 passed`
- live 앱 모델: `ollama:llama-3.3-70b-instruct-q4-k-m`
- live 질의 감사 로그:
  - `source_count=3`
  - `effective_index_mode=v2_only`
  - `graph_review_path_count=3`
  - `warning_codes=[]`

## 케이스 판정

- 케이스 A: Graph payload가 비어 있는데 모델이 구조화 리뷰 템플릿을 생성하는 경우
  - 백엔드 finalize, 세션 복원, 프론트 최종 렌더 모두 구조화 본문을 보존한다.
- 케이스 B: Graph payload에 `graph_review_paths`, `facts`, `clarification_questions` 등이 채워지는 경우
  - Graph payload 기반 패널을 렌더하고, 모델이 생성한 중복 구조화 텍스트는 제거한다.

## 추가 판단

DGX live 질의에서 `graph_review_path_count=3`이 기록되었으므로 `GRAPH_ENABLED` 런타임 비활성화가 원인은 아니다. Graph payload가 비는 상황은 질의별 Graph retrieval 결과가 없거나, retrieval 결과가 있어도 프론트에서 렌더 가능한 `graph_review_paths`, `facts`, clarification 관련 plan 필드가 비어 있는 경우로 판단한다.
