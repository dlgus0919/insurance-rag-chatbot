# Frontend Guide

신한EZ손해보험 보상지원 AI 챗봇의 모듈화 프론트엔드입니다. FastAPI가 `frontend/`를 same-origin으로 서빙하는 구조를 기본 개발 방식으로 사용합니다.

## 디렉토리 구조

```text
frontend/
├── index.html
├── css/
│   ├── variables.css
│   ├── base.css
│   ├── login.css
│   ├── chat.css
│   ├── admin.css
│   └── components.css
├── html/
│   ├── login.html
│   ├── chat.html
│   ├── admin.html
│   └── components.html
└── js/
    ├── app.js
    ├── config.js
    ├── api.js
    ├── storage.js
    ├── pages/
    ├── modules/
    └── ui/
```

## 로컬 실행

프로젝트 루트에서 FastAPI 서버를 실행합니다.

```bash
API_COOKIE_SECURE=false .venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 다음 주소를 엽니다.

```text
http://127.0.0.1:8000/login
```

정적 서버 3000을 별도로 사용할 수는 있지만, 기본 smoke test는 cookie와 CORS 변수를 줄이기 위해 `127.0.0.1:8000` same-origin 방식을 사용합니다.

## 주요 파일

- `js/app.js`: SPA 라우팅, 페이지 로드, 인증 상태 해석, 채팅/관리자 화면 연결
- `js/config.js`: API base URL, endpoint, localStorage key, 앱 상수
- `js/api.js`: 재사용 가능한 `fetchAPI` 래퍼
- `js/pages/*.js`: 페이지별 이벤트 바인딩
- `js/modules/*.js`: 인증, 세션, 관리자, 사이드바, 모달 등 도메인 모듈
- `js/ui/*.js`: 알림, 다이얼로그, 버튼, 입력 컴포넌트 보조 함수

## 인증 흐름

인증의 실제 기준은 서버가 발급하는 HttpOnly cookie입니다.

1. 로그인 폼 제출
2. `POST /api/auth/login`
3. 서버가 `access_token`, `refresh_token` cookie 발급
4. 응답의 `user`를 `localStorage.user_info`에 캐시
5. 새로고침 또는 직접 URL 접근 시 `/api/auth/me`로 cookie 인증 확인

`localStorage.auth_token`은 이전 토큰 기반 흐름과의 호환을 위한 보조 키이며, 현재 브라우저 인증의 기준으로 사용하지 않습니다.

## 페이지 추가 절차

1. `frontend/html/<page>.html`에 최상위 `<div id="page-..." class="page">`를 작성합니다.
2. 필요한 스타일을 기존 CSS 파일에 추가하거나 페이지 CSS를 분리합니다.
3. `frontend/js/pages/<page>.js`에 초기화 함수를 작성합니다.
4. `frontend/js/app.js`의 `PAGES`, `ROUTES`, `parseRoute`, `loadPageByRoute`에 라우트를 등록합니다.
5. `loadPageHTML(PAGES.X, 'page-x')`처럼 라우터가 현재 페이지에 `active` 클래스를 부여하게 합니다.

## 빌드

선택적 프로덕션 번들은 `esbuild`를 사용합니다.

```bash
cd frontend
npm install
npm run build
```

빌드 결과는 `frontend/dist/app.min.js`에 생성됩니다. 개발 환경의 `index.html`은 기본적으로 `/js/app.js`를 직접 로드합니다.

프로젝트 루트에서는 다음 스크립트도 사용할 수 있습니다.

```bash
scripts/build_frontend.sh
```

## 검증

```bash
find frontend/js -name '*.js' -print0 | xargs -0 -n1 node --check
API_COOKIE_SECURE=false .venv/bin/python -m pytest tests/test_api_auth_system.py tests/test_api_chat_stream.py tests/test_api_admin_users.py tests/test_api_admin_audit.py -q
npm run test:e2e
```
