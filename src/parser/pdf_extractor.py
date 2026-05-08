"""PDF 임베딩 이미지 직접 추출 유틸리티."""

from __future__ import annotations

import io
from pathlib import Path


def extract_page_image(pdf_path: str | Path, page_no: int):
    """
    PDF 페이지에서 임베딩된 이미지를 직접 추출한다.

    D6/D7 스캔 PDF처럼 페이지가 단일 JPEG 이미지인 경우 re-render 없이
    원본 이미지를 반환한다. 이미지가 없는 페이지는 300dpi 렌더링으로
    폴백한다. page_no는 0-indexed다.
    """

    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("PyMuPDF(fitz)가 설치되어 있지 않습니다.") from exc
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("Pillow가 설치되어 있지 않습니다.") from exc

    with fitz.open(str(pdf_path)) as doc:
        if page_no < 0 or page_no >= doc.page_count:
            raise IndexError(f"page_no가 범위를 벗어났습니다: {page_no} / {doc.page_count}")

        page = doc[page_no]
        images = page.get_images(full=True)
        if images:
            xref = max(images, key=lambda item: item[2] * item[3])[0]
            raw = doc.extract_image(xref)
            image = Image.open(io.BytesIO(raw["image"]))
            image.load()
            if image.mode not in ("L", "RGB"):
                image = image.convert("L")
            return image

        matrix = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        image.load()
        return image


def get_page_count(pdf_path: str | Path) -> int:
    """PDF 총 페이지 수를 반환한다."""

    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("PyMuPDF(fitz)가 설치되어 있지 않습니다.") from exc

    with fitz.open(str(pdf_path)) as doc:
        return doc.page_count
