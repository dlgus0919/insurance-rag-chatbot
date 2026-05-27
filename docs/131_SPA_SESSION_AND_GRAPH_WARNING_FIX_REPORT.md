# 131. SPA 세션 복구 및 GraphDB 경고 노출 수정 보고

작성일: 2026-05-26

## 문제 현상

FastAPI SPA 챗봇에서 첫 로그인 직후 기존 브라우저 저장소에 남아 있던 세션으로 질문하면 `해당 세션을 찾을 수 없습니다` 오류가 발생했다. 또한 GraphDB 구조화 근거가 정상 표시되는 경우에도 현재 선택된 VectorStore에서 일부 GraphDB 근거 chunk ID를 찾지 못했다는 처리 경고가 사용자 화면에 노출되었다.

## 원인

1. 브라우저 local/session storage에 이전 런타임 DB의 `session_id`가 남아 있고, 새 SQLite 런타임 DB에는 해당 세션이 없을 때 백엔드가 `SessionNotFoundException`을 반환했다.
2. GraphDB는 v2 manual chunk ID를 근거로 보유하지만, 사용자가 선택한 OCR 인덱스의 VectorStore에는 해당 chunk가 없을 수 있다. 이 경우 구조화 근거 자체는 유효하지만 보조 chunk를 RAG context에 추가하지 못한 상황을 사용자 경고로 표시하고 있었다.

## 수정 내용

- `src/api/routes/chat.py`
  - stale `session_id`가 들어오면 오류를 반환하지 않고 새 채팅 세션을 생성하도록 변경했다.
  - 새 세션 생성 로직을 `_create_session()`으로 분리했다.
- `frontend/js/pages/chat.js`
  - `/api/sessions` 응답 목록에 현재 저장된 세션 ID가 없으면 로컬 세션 상태를 자동 초기화하도록 변경했다.
- `src/api/rag_service.py`
  - GraphDB source chunk가 현재 VectorStore에 없는 경우 사용자-facing warning을 만들지 않고 서버 로그만 남기도록 변경했다.
  - GraphDB 조회 자체가 실패하는 경우의 경고는 유지했다.
- `tests/test_api_chat_stream.py`
  - stale session ID가 들어와도 SSE error 없이 새 세션과 메시지가 저장되는 회귀 테스트를 추가했다.
- `frontend/dist/app.min.js`
  - 프론트 변경 사항을 반영해 번들을 재생성했다.

## 검증

원격 DGX Spark main repo(`/srv/shared/projects/insurance-rag-chatbot`)에서 검증했다.

```bash
node --check frontend/js/pages/chat.js
.venv/bin/python -m py_compile src/api/routes/chat.py src/api/rag_service.py
PYTHONPATH=. .venv/bin/pytest tests/test_api_chat_stream.py -q
PYTHONPATH=. .venv/bin/pytest -q
cd frontend && npm run build
```

결과:

- `tests/test_api_chat_stream.py`: 2 passed
- 전체 pytest: 410 passed, 3 warnings
- 프론트 JS 문법 검사 및 esbuild 번들 생성 성공

## 남은 주의사항

GraphDB chunk 미조회는 숨겼지만, 선택한 OCR 인덱스에 따라 일부 GraphDB 근거 chunk가 일반 RAG source 목록에 합류하지 못하는 구조적 차이는 남아 있다. 구조화 근거 패널의 확정/후보/누락 표시는 그대로 유지되므로 답변 검증에는 영향을 주지 않는다.
