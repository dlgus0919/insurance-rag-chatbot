# Codex 명세 #48 — 신한EZ손해보험 브랜드 테마 적용

## 1) Goal

Streamlit 웹앱의 로그인 화면과 챗봇 UI를 신한EZ손해보험 공식 브랜드 아이덴티티에 맞게 꾸민다.

- 공식 색상 체계를 `.streamlit/config.toml`의 테마 설정에 반영한다.
- 로그인 화면과 사이드바 상단에 신한EZ 로고(또는 마스코트 이미지)를 삽입한다.
- 브랜드 CSS를 `st.markdown` HTML injection으로 보완한다.
- 기존 인증·채팅·관리자 기능은 일체 변경하지 않는다.

---

## 2) Background

현재 `.streamlit/config.toml`에는 `[theme]` 섹션이 없어 Streamlit 기본(흰색·회색) 테마가 적용된다.
로그인 화면은 단순 `st.title` + 컬럼 레이아웃이며, 로고나 브랜드 요소가 없다.

신한EZ손해보험은 신한금융그룹 계열사로, 공식 사이트(https://www.shinhanezins.co.kr)와
신한금융그룹 브랜드 가이드라인에서 색상·로고·마스코트를 확인할 수 있다.

---

## 3) Target Files

### 수정 허용
- `.streamlit/config.toml` — `[theme]` 섹션 추가
- `src/ui/streamlit_app.py` — 로고 삽입 및 CSS inject (기존 로직 변경 금지)

### 신규 생성
- `assets/logo.png` (또는 `assets/logo.svg`) — 다운로드한 신한EZ 로고
- `assets/mascot.png` — 마스코트 이미지 (획득 가능한 경우)
- `src/ui/brand.py` — 로고 로드·CSS inject 헬퍼 모듈

### 수정 금지
- `src/auth/`, `src/rag/`, `src/retrieval/`, `src/llm/`, `src/db/` 하위 모든 파일
- `scripts/` 하위 모든 파일
- `src/ui/admin_page.py`, `src/ui/chat_store.py`, `src/ui/pdf_view.py`

---

## 4) Detailed Requirements

### 4-1. 브랜드 색상 조사 (웹 탐색 필수)

구현 전 아래 URL을 직접 방문하여 공식 색상 값을 확인한다.

- https://www.shinhanezins.co.kr (신한EZ손해보험 공식 사이트)
- https://www.shinhangroup.com (신한금융그룹 브랜드 가이드)
- 검색: `신한EZ손해보험 CI` / `신한금융 브랜드 컬러` / `신한 파란색 hex`

확인해야 할 항목:
- Primary color (주 파란색 계열 hex 코드)
- Secondary / accent color
- 텍스트 색상
- 로고 이미지 URL (SVG 또는 PNG)
- 마스코트 이미지 URL (있는 경우)

조사 결과를 `docs/48_BRAND_RESEARCH.md`에 기록한 후 구현을 진행한다.
(색상 확인 불가 시: 신한금융그룹 대표색 `#0046FF` 계열로 fallback 적용하고 보고서에 명시)

### 4-2. `.streamlit/config.toml` 테마

```toml
[theme]
primaryColor       = "<조사한 primary hex>"
backgroundColor    = "#FFFFFF"
secondaryBackgroundColor = "#F4F7FC"   # 사이드바·카드 배경
textColor          = "#1A1A2E"
font               = "sans serif"
```

### 4-3. `src/ui/brand.py` 헬퍼 모듈

```python
"""신한EZ손해보험 브랜드 요소 주입 헬퍼."""

from pathlib import Path
import base64
import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"

BRAND_CSS = """
<style>
/* 로그인 카드 */
.login-card {
    background: #FFFFFF;
    border-radius: 16px;
    padding: 2.5rem 2rem;
    box-shadow: 0 4px 20px rgba(0, 70, 255, 0.08);
    border-top: 4px solid <primary_color>;
}
/* 사이드바 상단 로고 영역 */
.sidebar-logo {
    text-align: center;
    padding-bottom: 1rem;
    border-bottom: 1px solid #E8EDF5;
    margin-bottom: 1rem;
}
/* 헤더 강조 */
.app-header {
    color: <primary_color>;
    font-weight: 700;
}
/* 버튼 primary 색상은 config.toml primaryColor로 자동 적용 */
</style>
"""

def inject_css() -> None:
    """브랜드 CSS를 페이지에 주입한다."""
    st.markdown(BRAND_CSS, unsafe_allow_html=True)


def logo_base64(filename: str = "logo.png") -> str | None:
    """assets/ 디렉토리에서 로고를 base64로 인코딩한다."""
    path = ASSETS_DIR / filename
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode()


def render_logo(width: int = 160, filename: str = "logo.png") -> None:
    """로고 이미지를 st.image()로 렌더링한다."""
    path = ASSETS_DIR / filename
    if path.exists():
        st.image(str(path), width=width)
    else:
        st.markdown("**신한EZ손해보험**")


def render_sidebar_logo() -> None:
    """사이드바 상단에 로고를 렌더링한다."""
    path = ASSETS_DIR / "logo.png"
    if path.exists():
        st.markdown('<div class="sidebar-logo">', unsafe_allow_html=True)
        st.image(str(path), width=140)
        st.markdown("</div>", unsafe_allow_html=True)
```

### 4-4. `streamlit_app.py` 수정 지침

#### 공통 (페이지 최상단, `main()` 진입 직후)

```python
from src.ui.brand import inject_css, render_logo, render_sidebar_logo
inject_css()
```

#### 로그인 화면 (`_check_auth()` 내)

기존:
```python
st.title("보험 고시 문서 RAG 챗봇")
st.markdown("---")
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.subheader("🔐 임직원 전용 서비스")
```

변경 후:
```python
# 로고 중앙 정렬
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    render_logo(width=200)
    st.markdown(
        '<p style="text-align:center; color:#666; font-size:13px; margin-top:-8px;">'
        '임직원 전용 보험 문서 RAG 서비스</p>',
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.subheader("🔐 로그인")
```

#### 챗봇 메인 화면 (사이드바 상단)

`with st.sidebar:` 블록의 첫 줄에 추가:
```python
render_sidebar_logo()
```

#### 챗봇 메인 헤더

기존 `st.title("보험 고시 문서 RAG 챗봇")`을 아래로 교체:
```python
st.markdown(
    '<h1 class="app-header">📋 보험 문서 RAG 챗봇</h1>',
    unsafe_allow_html=True,
)
```

### 4-5. 로고·마스코트 이미지 획득

웹 탐색으로 공식 로고 이미지를 획득하여 `assets/logo.png`로 저장한다.
마스코트 이미지가 있다면 `assets/mascot.png`로 저장한다.

획득 우선순위:
1. 신한EZ 공식 사이트 img 태그에서 로고 URL 추출 → 다운로드
2. 신한금융그룹 미디어 자료실 → 로고 파일
3. 위키미디어 Commons 등 공개 소스
4. 획득 불가 시: `assets/logo.png`를 Python PIL로 텍스트 기반 placeholder 생성 (`신한EZ` 텍스트, primary color 배경)

로고를 커밋하기 전에 저작권 고지 여부를 `docs/48_BRAND_RESEARCH.md`에 명시한다.
사내 사용 목적이므로 공식 CI 이미지 사용은 통상 허용되나, 외부 배포 전 법무 확인을 권고한다.

### 4-6. `assets/` 디렉토리

- `assets/` 폴더를 신규 생성한다.
- `assets/.gitkeep`을 추가하여 빈 폴더도 git에 포함시킨다.
- `.gitignore`에 이미 `*.pdf`, `*.xlsx` 규칙이 있으나 `assets/`는 제외 대상이 아니므로 별도 조치 불필요.

---

## 5) Validation

```bash
# 1. 모듈 임포트 확인
python -c "from src.ui.brand import inject_css, render_logo; print('OK')"

# 2. 기존 테스트 회귀
pytest -q
# 목표: 201 passed (기존 수), 0 failures

# 3. 로컬 앱 실행 후 육안 확인
streamlit run src/ui/streamlit_app.py
# 확인 항목:
#   - 로그인 화면: 로고 표시, 브랜드 색 버튼
#   - 사이드바 상단: 로고 표시
#   - 챗봇 헤더: 브랜드 색 타이틀
#   - 기존 로그인·채팅·관리자 기능 정상 동작
```

---

## 6) Stop Rules

- 기존 테스트 1건이라도 실패 → 즉시 중단, 보고
- `src/auth/`, `src/rag/`, `src/retrieval/` 등 비UI 파일 수정이 필요해지는 경우 → 중단, 보고
- 로고 이미지 URL을 웹에서 전혀 찾을 수 없는 경우 → placeholder 생성 후 보고서에 명시하고 계속 진행
- Streamlit 앱 실행 자체가 오류로 실패하는 경우 → 즉시 중단, 스택 트레이스 보고

---

## 7) Output Requirements

구현 완료 후 `docs/48_SHINHANEZ_BRANDING_REPORT.md`를 작성하고 커밋한다.

보고서 포함 항목:
1. 조사한 브랜드 색상 값 (hex 코드, 출처 URL)
2. 로고·마스코트 이미지 획득 경로 및 저장 파일명
3. 변경된 파일 목록 (함수/섹션별 한 줄 설명)
4. `pytest -q` 전체 출력
5. 로컬 앱 로그인·챗봇 화면 스크린샷 또는 육안 확인 내용
6. 잔여 블로커 (없으면 "None")

`assets/logo.png`, `assets/mascot.png`는 커밋에 포함한다.
JSON 결과 파일·HTML 파일은 커밋하지 않는다.
