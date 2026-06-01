# 168. Workspace Feature Merge Report

작성일: 2026-06-01  
대상 프로젝트: `insurance-rag-chatbot`  
작업 브랜치: `codex/merge-workspace-features-20260601`

## 개요

이 문서는 `dani` 워크스페이스의 명확화 UX 구현과 `maeng` 워크스페이스의 관리자 진단 탭 고도화 작업을 현재 메인 코드베이스 기준으로 재통합한 결과를 요약한다.

## 편입한 기능

### 1. 명확화 UX 완성 (`dani` 작업 기반)
- 일반 질의 결과에 `clarification_questions`, `ambiguous_terms`, `term_correction_candidates`가 있으면 대화 버블 안에 상호작용형 명확화 패널을 노출하도록 반영했다.
- 사용자는 실손 세대, 방문 구분, 상품/특약, 치료 목적, 증빙 서류를 버튼 기반으로 선택할 수 있다.
- 자주 쓰는 조합 프리셋을 추가했다.
- 선택값을 반영해 같은 세션/같은 모드로 재검색하도록 반영했다.
- 백엔드 요청 스키마에 `clarification` payload를 추가했다.

### 2. 관리자 진단 탭 고도화 (`maeng` 작업 기반)
- 관리자 통계에 모델 품질 지표(`model_quality_stats`)와 이슈 집계(`issue_stats`)를 추가했다.
- 최근 RAG 진단 화면에 명확화/모호성/Graph review path 관련 정보가 노출되도록 보강했다.
- `graph-sync-status` API와 내보내기 기능을 추가했다.
- GraphDB-VectorStore sync 카드와 별도로, 그래프 빌드 메타데이터 기반 상태를 관리자 화면에서 확인할 수 있게 했다.

## 메인 코드 기준 재조정 내용
- 현재 메인 브랜치에 이미 있던 GraphDB-VectorStore sync 진단과 충돌하지 않도록, 관리자 화면 개선은 기존 기능 위에 확장하는 형태로 유지했다.
- 프론트엔드 정적 자산 캐시 버전 문자열을 통합해 오래된 JS/CSS가 섞여 로드되지 않도록 정리했다.
- 충돌은 `frontend/index.html`, `frontend/js/app.js` 두 파일의 캐시 버전 문자열에서만 발생했으며 기능 충돌은 없었다.

## 변경 파일
- `frontend/css/chat.css`
- `frontend/index.html`
- `frontend/js/app.js`
- `frontend/js/config.js`
- `frontend/js/modules/admin.js`
- `frontend/js/pages/admin.js`
- `frontend/js/pages/chat.js`
- `src/api/routes/admin.py`
- `src/api/routes/chat.py`
- `src/api/schemas/chat.py`
- `tests/e2e/chat.spec.js`
- `tests/test_api_admin.py`

## 검증

### 실행한 검증
```bash
node --check frontend/js/app.js
node --check frontend/js/config.js
node --check frontend/js/modules/admin.js
node --check frontend/js/pages/admin.js
node --check frontend/js/pages/chat.js
.venv/bin/python -m py_compile src/api/routes/admin.py src/api/routes/chat.py src/api/schemas/chat.py
.venv/bin/pytest -q tests/test_api_admin.py tests/test_api_chat_stream.py tests/test_api_rag_service_payload.py tests/test_admin_page.py
.venv/bin/pytest -q tests/test_api_admin_users.py tests/test_api_admin_audit.py tests/test_api_system_status.py tests/test_api_security.py tests/test_api_rbac.py
git diff --check
```

### 결과
- 문법/임포트 검증: 통과
- 관리자/채팅 관련 pytest: `14 passed`
- 인접 관리자/보안 회귀 pytest: `22 passed`
- `git diff --check`: 통과

### 실행하지 못한 검증
- `tests/e2e/chat.spec.js` Playwright 실행은 원격 환경에 `@playwright/test` 패키지가 없어 수행하지 못했다.

## 남은 위험
- 명확화 UX의 브라우저 상호작용 회귀는 Playwright 환경이 준비된 뒤 한 번 더 확인하는 것이 바람직하다.
- 현재 작업은 통합 브랜치에만 반영되어 있으며, 아직 커밋/푸시는 수행하지 않았다.
