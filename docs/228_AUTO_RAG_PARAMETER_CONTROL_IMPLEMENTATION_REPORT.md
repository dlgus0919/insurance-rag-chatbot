# 228. 일반 질의 자동 파라미터 조절 구현 보고서

## 구현 범위

- `src/rag/auto_params.py`를 추가해 일반 질의의 `Top-K`와 `temperature`를 `SearchIntentPlan` 기반 규칙으로 자동 산출한다.
- `/chat/stream`은 `auto_params`가 켜져 있고 최종 route가 `general`일 때만 자동값을 적용한다.
- `quickcode`, `formal`, 보험금 계산 전용 로직은 기존 전용 Top-K/temperature 정책을 유지한다.
- audit/debug에는 요청값과 적용값을 모두 남긴다.
- reranker 점수 payload를 `DebugInfo.reranker_scores`와 RAG diagnostics에 기록해 이후 adaptive-k threshold 평가에 사용할 수 있게 했다.
- SPA 일반 질의 UI는 기본 자동 설정 토글을 제공하고, 자동 ON 상태에서는 수동 Top-K/온도 슬라이더를 접는다.
- OCR 인덱스 선택에서 `기본 운영 인덱스`를 제거하고, 채팅/보험금 계산 API에서 `default` 요청도 `v2_only`로 보정한다.

## 안전 장치

- 자동 파라미터는 LLM이 아니라 deterministic rule table로 결정한다.
- 서버 기본 모드는 `AUTO_RAG_PARAMS_MODE=apply`이며, `off|observe|apply`를 지원한다.
- `AUTO_RAG_ALLOW_MANUAL_OVERRIDE=true`일 때 UI 토글 OFF로 수동값을 사용할 수 있다.
- 실무 답변의 production temperature는 기본 최대 `0.2`로 제한한다.
- 앱 startup prewarm도 `v2_only` 인덱스만 예열해 OCR 보정본 누락 경로를 줄였다.

## 검증

- `python -m py_compile src/rag/auto_params.py src/api/routes/chat.py src/api/routes/claim.py src/api/schemas/chat.py src/api/schemas/claim.py src/retrieval/reranker.py src/rag/pipeline.py`
- `find frontend/js -name '*.js' -print0 | xargs -0 -n1 node --check`
- `cd frontend && npm run build`
- `python -m pytest tests/test_auto_rag_params.py tests/test_reranker.py -q`

로컬 Python 환경에는 `fastapi`, `aiosqlite`가 없어 API 테스트는 DGX `.venv`에서 추가 검증해야 한다.
