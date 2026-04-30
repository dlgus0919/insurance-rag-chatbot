from src.retrieval import Hit
from scripts.eval import answer_mentions_expected_page, filter_chunks_by_doc, hit_matches_expected_page


def test_hit_matches_expected_page_range() -> None:
    hit = Hit(id="a", score=1.0, document="", metadata={"page_start": 10, "page_end": 12})

    assert hit_matches_expected_page(hit, [11]) is True
    assert hit_matches_expected_page(hit, [13]) is False


def test_answer_mentions_expected_page() -> None:
    assert answer_mentions_expected_page("답변입니다. [출처: 제1절, p.101]", [101]) is True
    assert answer_mentions_expected_page("답변입니다. [출처: 제1절, p.101]", [100]) is False


def test_answer_mentions_page_range_format() -> None:
    """범위 형식(p.36-38)도 expected_page가 범위 안에 있으면 정답으로 인정한다."""

    assert answer_mentions_expected_page("[출처: 약관, 제4조, p.36-38]", [38]) is True
    assert answer_mentions_expected_page("[출처: 약관, p.78-84]", [80]) is True
    assert answer_mentions_expected_page("[출처: 약관, p.78-84]", [82]) is True
    assert answer_mentions_expected_page("[출처: 약관, p.36-38]", [40]) is False
    assert answer_mentions_expected_page("[출처: 심평원, p.101]", [101]) is True
    assert answer_mentions_expected_page("[출처: 심평원, p.101]", [100]) is False


def test_filter_chunks_by_doc() -> None:
    chunks = [
        Hit(id="a", score=1.0, document="", metadata={"doc_short": "심평원"}),
        Hit(id="b", score=1.0, document="", metadata={"doc_short": "약관"}),
    ]

    assert [chunk.id for chunk in filter_chunks_by_doc(chunks, ["약관"])] == ["b"]
    assert filter_chunks_by_doc(chunks, None) == chunks
