from pathlib import Path

from src.config import PdfSource
from src.parser.chunker import chunk_pages


def test_header_context_and_codes_are_propagated() -> None:
    pages = [
        (
            1,
            """
            제1편 행위 급여 목록
            제1부 일반원칙
            제2장 기본진료료
            제1절 진찰료

            AA157 재진 진찰료는 10100 규정을 따른다.
            """,
        )
    ]

    chunks = chunk_pages(pages, target_chars=500, overlap_chars=50)

    assert len(chunks) == 1
    metadata = chunks[0].metadata
    assert metadata["volume"] == "제1편 행위 급여 목록"
    assert metadata["part"] == "제1부 일반원칙"
    assert metadata["chapter"] == "제2장 기본진료료"
    assert metadata["section"] == "제1절 진찰료"
    assert metadata["page_start"] == 1
    assert metadata["page_end"] == 1
    assert set(metadata["codes"]) == {"AA157", "10100"}


def test_section_change_splits_chunks_on_same_page() -> None:
    pages = [
        (
            3,
            """
            제1장 검사료
            제1절 혈액검사
            AA100 혈액검사 내용
            제2절 영상검사
            B5070 영상검사 내용
            """,
        )
    ]

    chunks = chunk_pages(pages, target_chars=500, overlap_chars=50)

    assert [chunk.metadata["section"] for chunk in chunks] == ["제1절 혈액검사", "제2절 영상검사"]
    assert chunks[0].metadata["codes"] == ["AA100"]
    assert chunks[1].metadata["codes"] == ["B5070"]


def test_long_text_without_section_uses_sliding_window() -> None:
    long_text = "가" * 120
    pages = [(5, f"제1장 긴본문\n{long_text}")]

    chunks = chunk_pages(pages, target_chars=50, overlap_chars=10)

    assert len(chunks) >= 3
    assert all(chunk.metadata["page_start"] == 5 for chunk in chunks)
    assert all(chunk.metadata["chapter"] == "제1장 긴본문" for chunk in chunks)
    assert all(chunk.metadata["char_count"] <= 50 for chunk in chunks)


def test_insurance_policy_headers() -> None:
    """약관 헤더 패턴이 제N조(...) 형식을 올바르게 인식한다."""

    sample = [
        (37, "제3조(보장종목별 보상내용)\n① 회사는 이 약관에 따라 보상합니다."),
        (38, "5. 요실금(N39.3, N39.4, R32)\n다음 사유는 보상하지 않습니다"),
    ]
    dummy_source = PdfSource(
        path=Path("dummy.pdf"),
        doc_type="insurance_policy",
        doc_name="테스트 약관",
        doc_short="테스트약관",
    )

    chunks = chunk_pages(sample, doc_source=dummy_source)

    assert any(c.metadata.get("chapter", "").startswith("제3조") for c in chunks)


def test_icd10_code_extraction() -> None:
    """ICD-10 코드(소수점 포함)가 metadata.codes에 추출된다."""

    sample = [(1, "요실금(N39.3, N39.4, R32)은 보상하지 않습니다.")]
    dummy_source = PdfSource(
        path=Path("dummy.pdf"),
        doc_type="insurance_policy",
        doc_name="테스트",
        doc_short="테스트",
    )

    chunks = chunk_pages(sample, doc_source=dummy_source)
    codes = chunks[0].metadata["codes"]

    assert "N39.3" in codes
    assert "N39.4" in codes
    assert "R32" in codes


def test_chunk_id_includes_doc_short() -> None:
    """멀티 문서 청크 ID에 doc_short가 포함된다."""

    sample = [(1, "테스트 내용입니다.")]
    dummy_source = PdfSource(
        path=Path("dummy.pdf"),
        doc_type="insurance_policy",
        doc_name="테스트",
        doc_short="약관",
    )

    chunks = chunk_pages(sample, doc_source=dummy_source)

    assert chunks[0].id.startswith("약관_")
    assert chunks[0].metadata["doc_short"] == "약관"


def test_missing_pdf_skipped(tmp_path: Path) -> None:
    """존재하지 않는 PDF는 ingest 시 건너뛰고 에러를 발생시키지 않는다."""

    missing = PdfSource(
        path=tmp_path / "없는파일.pdf",
        doc_type="guide_book",
        doc_name="없음",
        doc_short="가이드북",
    )

    assert not missing.path.exists()
