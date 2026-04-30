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
    assert metadata["codes"] == ["AA157", "10100"]


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
