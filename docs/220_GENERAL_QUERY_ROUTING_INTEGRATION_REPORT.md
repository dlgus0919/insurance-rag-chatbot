# 220. General Query Routing Integration Report

## Summary

dani PR의 일반 질의 검색 전략 통합안을 DGX 메인 로직에 맞게 변형해 반영했다. 사용자 기본 화면에서는 일반 질의를 중심으로 유지하고, 내부 라우터가 필요할 때 기존 퀵 코드 검색 또는 약관 정형 검색 전략을 재사용한다.

## Adjustments From PR

- `src/rag/query_router.py`
  - 일반 질의를 `general`, `quickcode`, `formal` 중 하나로 자동 라우팅한다.
  - `route_reason`, `matched_cues`를 추가해 운영 감사 로그에서 라우팅 근거를 확인할 수 있게 했다.
- `src/api/routes/chat.py`
  - `mode=general` 요청에서만 자동 라우팅을 수행한다.
  - 기존 `mode=quickcode`, `mode=formal` 및 호환 endpoint는 유지한다.
  - audit detail에 `resolved_route`, `resolved_intent`, `route_reason`, `matched_cues`를 기록한다.
- `src/api/rag_service.py`
  - 자동 라우팅된 formal 검색은 문서 필터를 강제하지 않는다.
  - 명시 formal 검색은 기존처럼 기본 `["약관"]` 범위를 유지한다.
- `frontend/html/chat.html`, `frontend/js/pages/chat.js`
  - 정적 웹 기본 UI에서 퀵 코드/약관 정형 검색 탭과 dead handler를 제거했다.
  - `frontend/dist/app.min.js`를 재빌드했다.
- `src/ui/streamlit_app.py`
  - 기본 검색 모드는 `일반 질의`로 통합했다.
  - 운영/개발 진단을 위해 명시 퀵 코드/약관 정형 검색은 `고급 검색` 탭 아래에 보존했다.

## Validation

Local:

```bash
python -m pytest tests/test_query_router.py -q
git diff --check
python -m compileall -q src/rag/query_router.py src/api/rag_service.py src/api/routes/chat.py src/ui/streamlit_app.py
npm install
npm run build
```

DGX validation is required after push because local Python does not include the API test dependency `aiosqlite`.

## Operational Notes

이 변경은 온톨로지/GraphDB 산출물을 수정하지 않는다. 자동 라우팅은 일반 질의 입력을 기존 전략으로 내부 분기하는 API/UI 동작 변경이며, 명시 정형 검색의 기존 약관 기본 범위는 유지된다.
