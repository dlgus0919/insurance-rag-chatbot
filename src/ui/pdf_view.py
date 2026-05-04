"""PDF 페이지 렌더링 및 OS 파일 열기 헬퍼."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import streamlit as st


@st.cache_data(max_entries=64, show_spinner=False)
def render_pdf_page_png(pdf_path: str, page_no: int, dpi: int = 150) -> bytes:
    """PDF 1페이지를 PNG 바이트로 렌더링한다. page_no는 1부터 시작한다."""

    import fitz

    doc = fitz.open(pdf_path)
    try:
        page = doc[page_no - 1]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def open_pdf_in_native_viewer(pdf_path: Path) -> tuple[bool, str]:
    """OS 기본 PDF 뷰어로 파일을 연다. macOS에서만 지원한다."""

    if not pdf_path.exists():
        return False, f"파일을 찾을 수 없습니다: {pdf_path}"
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(pdf_path)])
        return True, f"Preview에서 {pdf_path.name}을(를) 열었습니다."
    return False, "이 기능은 macOS에서만 동작합니다."
