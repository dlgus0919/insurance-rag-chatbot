from src.retrieval import Hit
from scripts.eval import answer_mentions_expected_page, hit_matches_expected_page


def test_hit_matches_expected_page_range() -> None:
    hit = Hit(id="a", score=1.0, document="", metadata={"page_start": 10, "page_end": 12})

    assert hit_matches_expected_page(hit, [11]) is True
    assert hit_matches_expected_page(hit, [13]) is False


def test_answer_mentions_expected_page() -> None:
    assert answer_mentions_expected_page("답변입니다. [출처: 제1절, p.101]", [101]) is True
    assert answer_mentions_expected_page("답변입니다. [출처: 제1절, p.101]", [100]) is False
