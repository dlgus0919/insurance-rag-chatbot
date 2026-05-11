"""신한EZ손해보험 브랜드 요소 주입 헬퍼."""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
PRIMARY_COLOR = "#0046FF"
ROYAL_BLUE = "#2878F5"
LIGHT_BLUE = "#8CD2F5"
TEXT_COLOR = "#1A1A2E"

BRAND_CSS = f"""
<style>
:root {{
    --shinhanez-primary: {PRIMARY_COLOR};
    --shinhanez-royal: {ROYAL_BLUE};
    --shinhanez-light: {LIGHT_BLUE};
    --shinhanez-text: {TEXT_COLOR};
}}

.login-card {{
    background: #FFFFFF;
    border-radius: 16px;
    padding: 2rem 1.75rem;
    box-shadow: 0 4px 20px rgba(0, 70, 255, 0.08);
    border-top: 4px solid var(--shinhanez-primary);
}}

.brand-logo {{
    display: flex;
    justify-content: center;
    align-items: center;
    margin: 0.75rem 0 0.25rem;
}}

.brand-logo img {{
    display: block;
    height: auto;
    max-width: 100%;
}}

.sidebar-logo {{
    text-align: center;
    padding: 0.25rem 0 1rem;
    border-bottom: 1px solid #E8EDF5;
    margin-bottom: 1rem;
}}

.sidebar-logo img {{
    display: inline-block;
    height: auto;
    max-width: 100%;
}}

.app-header {{
    color: var(--shinhanez-primary);
    font-weight: 700;
    letter-spacing: 0;
    margin: 0.25rem 0 1rem;
}}

.login-subtitle {{
    text-align: center;
    color: #5F6B7A;
    font-size: 13px;
    margin: -0.25rem 0 0.75rem;
}}

div.stButton > button[kind="primary"] {{
    border-color: var(--shinhanez-primary);
    background: var(--shinhanez-primary);
}}

div.stButton > button[kind="primary"]:hover {{
    border-color: var(--shinhanez-royal);
    background: var(--shinhanez-royal);
}}
</style>
"""


def inject_css() -> None:
    """브랜드 CSS를 페이지에 주입한다."""

    st.markdown(BRAND_CSS, unsafe_allow_html=True)


def logo_base64(filename: str = "logo.png") -> str | None:
    """assets 디렉터리에서 이미지를 base64로 인코딩한다."""

    path = ASSETS_DIR / filename
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _image_html(filename: str, width: int, alt: str, css_class: str) -> str | None:
    encoded = logo_base64(filename)
    if encoded is None:
        return None
    return (
        f'<div class="{css_class}">'
        f'<img src="data:image/png;base64,{encoded}" width="{width}" alt="{alt}" />'
        "</div>"
    )


def render_logo(width: int = 200, filename: str = "logo.png") -> None:
    """로고 이미지를 중앙 정렬해 렌더링한다."""

    html = _image_html(filename, width, "신한EZ손해보험", "brand-logo")
    if html is None:
        st.markdown("**신한EZ손해보험**")
        return
    st.markdown(html, unsafe_allow_html=True)


def render_sidebar_logo(width: int = 150) -> None:
    """사이드바 상단에 로고를 렌더링한다."""

    html = _image_html("logo.png", width, "신한EZ손해보험", "sidebar-logo")
    if html is None:
        st.markdown('<div class="sidebar-logo"><strong>신한EZ손해보험</strong></div>', unsafe_allow_html=True)
        return
    st.markdown(html, unsafe_allow_html=True)
