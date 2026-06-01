# 152. Admin Dashboard Live Connection Report

작성일: 2026-05-28  
대상 프로젝트: `insurance-rag-chatbot`

## 1. 목적

관리자 페이지의 다음 탭이 정적 목업이 아니라 실제 서버 상태를 읽도록 연결했다.

- 통계
- 시스템 상태
- 검색 진단

## 2. 핵심 변경

### 백엔드

- `GET /api/admin/stats`
  - `AuditLog`, `ChatMessage` 기반 실집계 반환
  - 총 질문 수, 총 응답 수, 평균 응답시간, 평균 근거 수, 검색 모드 분포, 사용자 분포, 모델 분포, 일별 사용량 제공

- `GET /api/admin/system-summary`
  - 기본/보정본/통합 인덱스별 BM25 및 Chroma 존재 여부 반환
  - GraphDB, 표준코드 DB, 사용자 파일 존재 여부 반환
  - 기본 LLM 설정값, 사용 가능 모델 목록, 임베딩 설정 반환

- `GET /api/admin/rag-diagnostics/latest`
  - 최근 일반 질의의 실제 검색 단계 진단 정보를 반환
  - 질의 미리보기, 모델, 인덱스 모드, 단계별 상태/소요시간, 경고를 포함

- 일반 질의 처리 시 `CHAT_QUERY` 감사 로그에 `rag_diagnostics`를 함께 저장하도록 변경

### 프론트엔드

- 관리자 페이지 초기 로딩 시 `stats`, `system-summary`, `rag-diagnostics`를 모두 조회
- 통계 탭:
  - 실데이터 기반 KPI 카드, 검색 모드 분포, 사용자별/모델별 막대 차트 렌더링
- 시스템 상태 탭:
  - 인덱스, 핵심 자산, LLM 기본 설정, 임베딩 설정을 실데이터로 렌더링
- 검색 진단 탭:
  - 최근 일반 질의의 BM25, dense, RRF, final, LLM 단계 결과를 표로 렌더링
- 탭 전환 시 각 탭이 다시 실제 API를 호출하도록 갱신

## 3. 변경 파일

- `src/api/routes/admin.py`
- `src/api/routes/chat.py`
- `src/api/rag_service.py`
- `frontend/js/config.js`
- `frontend/js/modules/admin.js`
- `frontend/js/pages/admin.js`
- `frontend/js/app.js`
- `frontend/index.html`
- `tests/test_api_admin.py`
- `tests/test_api_chat_stream.py`

## 4. 검증

### 로컬 정적 검증

```bash
node --check frontend/js/pages/admin.js
node --check frontend/js/modules/admin.js
PYTHONPYCACHEPREFIX=/private/tmp/codex_pycache python3 -m py_compile \
  src/api/routes/admin.py \
  src/api/routes/chat.py \
  src/api/rag_service.py \
  tests/test_api_admin.py \
  tests/test_api_chat_stream.py
```

### DGX 회귀 테스트

```bash
ssh ai-hang@100.88.5.57 \
  "cd /srv/shared/projects/insurance-rag-chatbot && \
   .venv/bin/pytest -q tests/test_api_admin.py tests/test_api_chat_stream.py"
```

결과:

- `5 passed, 1 warning`

### DGX 라이브 API 확인

`testAdmin` 관리자 계정 기준 `TestClient`로 실제 관리자 라우트를 확인했다.

확인 결과:

- `/api/admin/stats` -> `200`
- `/api/admin/system-summary` -> `200`
- `/api/admin/rag-diagnostics/latest` -> `200`

## 5. 주의사항

- 검색 진단 탭은 현재 `일반 질의`의 최근 감사 로그 기준으로만 데이터를 보여준다.
- 퀵 코드 검색, 약관 정형 검색, 보험금 계산 모드는 별도 진단 저장을 하지 않으면 표시되지 않는다.
- 작업 트리에는 본 작업과 무관한 기존 변경(`docs/142_GRAPHDB_CURRENT_STATE_REPORT.md`, `docs/151_GRAPHDB_BUILD_PIPELINE_DEFECT_REPORT.md`, `graph_viz/`, `frontend/js/api.js`)이 남아 있으므로 커밋 시 범위를 분리해야 한다.
