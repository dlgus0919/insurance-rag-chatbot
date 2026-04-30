"""PDF 텍스트 추출기."""

from __future__ import annotations

from pathlib import Path


def _parse_with_pymupdf(pdf_path: Path) -> list[tuple[int, str]]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("PyMuPDF가 설치되어 있지 않아 PDF를 파싱할 수 없습니다.") from exc

    pages: list[tuple[int, str]] = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            try:
                pages.append((index, page.get_text("text") or ""))
            except Exception as exc:  # pragma: no cover - 손상 PDF 방어
                print(f"[경고] {index}페이지 텍스트 추출 실패(PyMuPDF): {exc}")
                pages.append((index, ""))
    return pages


def parse_pdf(pdf_path: Path) -> list[tuple[int, str]]:
    """
    PDF를 페이지 단위로 텍스트 추출한다.

    pdfplumber를 우선 사용하고, 라이브러리가 없거나 빈 페이지가 나오면
    PyMuPDF 결과로 보완한다. 추출 실패 페이지는 빈 문자열로 포함한다.
    """

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

    pdfplumber_pages: list[tuple[int, str]] = []
    try:
        import pdfplumber

        with pdfplumber.open(str(pdf_path)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                try:
                    pdfplumber_pages.append((index, page.extract_text() or ""))
                except Exception as exc:  # pragma: no cover - 손상 페이지 방어
                    print(f"[경고] {index}페이지 텍스트 추출 실패(pdfplumber): {exc}")
                    pdfplumber_pages.append((index, ""))
    except ImportError:
        print("[정보] pdfplumber가 없어 PyMuPDF로 PDF를 파싱합니다.")
        return _parse_with_pymupdf(pdf_path)
    except Exception as exc:
        print(f"[경고] pdfplumber 파싱 실패, PyMuPDF로 폴백합니다: {exc}")
        return _parse_with_pymupdf(pdf_path)

    if not any(text.strip() for _, text in pdfplumber_pages):
        print("[정보] pdfplumber 추출 결과가 비어 PyMuPDF로 폴백합니다.")
        return _parse_with_pymupdf(pdf_path)

    if all(text.strip() for _, text in pdfplumber_pages):
        return pdfplumber_pages

    pymupdf_pages = dict(_parse_with_pymupdf(pdf_path))
    merged: list[tuple[int, str]] = []
    for page_no, text in pdfplumber_pages:
        if text.strip():
            merged.append((page_no, text))
            continue
        fallback = pymupdf_pages.get(page_no, "")
        if not fallback.strip():
            print(f"[경고] {page_no}페이지 텍스트가 비어 있습니다.")
        merged.append((page_no, fallback))
    return merged
