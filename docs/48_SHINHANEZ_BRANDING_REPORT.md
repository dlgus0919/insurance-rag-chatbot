# 48 신한EZ손해보험 브랜드 테마 적용 보고서

## 1. 브랜드 색상 및 출처

- Primary: `#0046FF` — 신한금융그룹 CI 페이지의 Shinhan Blue
- Secondary: `#8CD2F5`, `#4BAFF5`, `#2878F5`, `#00236E` — 신한금융그룹 CI 페이지의 보조색 계열
- Background: `#FFFFFF`
- Sidebar/card background: `#F4F7FC`
- Text: `#1A1A2E`
- 출처:
  - https://www.shinhangroup.com/kr/about/identity/ci
  - https://www.shinhanez.co.kr/static/cmy/CMY10010M01.html
  - https://www.shinhangroup.com/kr/about/identity/character

상세 조사 기록은 `docs/48_BRAND_RESEARCH.md`에 작성했다.

## 2. 로고·마스코트 획득

- `assets/logo.svg`: 신한EZ손해보험 공식 브랜드 페이지의 BI SVG 원본을 다운로드했다.
- `assets/logo.png`: 위 SVG를 로컬에서 PNG로 변환한 뒤 여백을 crop했다. Streamlit 표시 기본 파일로 사용한다.
- `assets/mascot.png`: 신한금융그룹 공식 캐릭터 페이지의 신한프렌즈 이미지를 다운로드했다.
- 신한EZ 전용 마스코트 이미지는 별도 공식 경로를 확인하지 못해, 그룹 공식 대표 캐릭터 이미지를 사용했다.

## 3. 변경 파일

- `.streamlit/config.toml`: `[theme]` 섹션을 추가해 Shinhan Blue 기반 Streamlit 테마를 적용했다.
- `src/ui/brand.py`: 브랜드 CSS 주입, 로고 base64 로딩, 로그인/사이드바 로고 렌더링 헬퍼를 추가했다.
- `src/ui/streamlit_app.py`: `inject_css()` 호출, 로그인 화면 로고, 사이드바 상단 로고, 브랜드 컬러 메인 헤더를 적용했다.
- `assets/.gitkeep`: assets 디렉터리 추적용 파일을 추가했다.
- `assets/logo.png`, `assets/logo.svg`, `assets/mascot.png`: 브랜드 표시용 자산을 추가했다.
- `docs/48_BRAND_RESEARCH.md`: 공식 색상/자산 조사 결과와 사용 주의 사항을 기록했다.

금지 범위인 `src/auth/`, `src/rag/`, `src/retrieval/`, `src/llm/`, `src/db/`, `scripts/`, `src/ui/admin_page.py`, `src/ui/chat_store.py`, `src/ui/pdf_view.py`는 수정하지 않았다.

## 4. 검증 결과

### 모듈 임포트

```bash
python -c "from src.ui.brand import inject_css, render_logo; print('OK')"
```

결과:

```text
OK
```

### 전체 테스트

```bash
pytest -q
```

결과:

```text
201 passed, 5 warnings in 2.02s
```

경고는 기존 PDF extractor 테스트에서 발생하는 SWIG 타입 DeprecationWarning이며 실패는 없다.

### Streamlit 실행

```bash
streamlit run src/ui/streamlit_app.py --server.headless true --server.port 8507
```

결과:

```text
Local URL: http://localhost:8507
```

추가로 `curl -L http://localhost:8507` smoke check를 수행해 Streamlit 서버가 HTML을 반환하는 것을 확인했다.

## 5. 화면 확인 내용

- 로그인 화면 코드 경로에서 `render_logo(width=220)`이 로그인 입력 위에 렌더링되도록 변경했다.
- 로그인 보조 문구와 구분선을 로고 아래에 배치하고, 로그인 버튼은 Streamlit theme primary color를 사용한다.
- 인증 후 사이드바 첫 줄에 `render_sidebar_logo()`가 실행되도록 배치했다.
- 메인 챗봇 화면의 기존 `st.title(...)`은 `<h1 class="app-header">📋 보험 문서 RAG 챗봇</h1>`로 교체해 `#0046FF` 브랜드 컬러를 적용했다.

자동 브라우저 스크린샷은 현재 Codex 세션에 `playwright`, `playwright-core`, `puppeteer`, `selenium-webdriver` 패키지가 없어 수행하지 못했다. 대신 Streamlit 기동, HTTP smoke check, 임포트 검증, 전체 테스트로 런타임 오류가 없음을 확인했다.

## 6. Git

- 구현 커밋: `34fc2a8` (`Apply Shinhanez branding theme`)
- Push: `origin/master`로 완료

## 7. 잔여 블로커

None
