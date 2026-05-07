from pathlib import Path

from src.config import PdfSource, indexed_pdf_sources


def test_indexed_pdf_sources_use_cloud_safe_not_file_existence() -> None:
    sources = [
        PdfSource(
            path=Path("/does/not/exist/d1.pdf"),
            doc_type="policy_act",
            doc_name="심평원",
            doc_short="심평원",
            cloud_safe=True,
        ),
        PdfSource(
            path=Path("/does/not/exist/d5.pdf"),
            doc_type="guide_book",
            doc_name="가이드북",
            doc_short="가이드북",
            cloud_safe=False,
        ),
        PdfSource(
            path=Path("/does/not/exist/d7.pdf"),
            doc_type="case_book_scanned",
            doc_name="상담사례집",
            doc_short="상담사례집",
            cloud_safe=True,
            requires_ocr=True,
        ),
    ]

    indexed = indexed_pdf_sources(sources)

    assert [source.doc_short for source in indexed] == ["심평원"]
