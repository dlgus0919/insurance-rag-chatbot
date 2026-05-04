from src.parser.chunker import Chunk
from src.rag.quick_code import build_quick_code_prompt, determine_doc_filter, merge_doc_filters


def test_determine_doc_filter_by_coverage_option() -> None:
    assert determine_doc_filter(False) == ["심평원"]
    assert determine_doc_filter(True) == ["심평원", "약관"]


def test_merge_doc_filters_preserves_order_and_deduplicates() -> None:
    assert merge_doc_filters(["심평원", "약관"], ["약관", "가이드북"]) == ["심평원", "약관", "가이드북"]


def test_build_quick_code_prompt_reflects_options() -> None:
    chunk = Chunk(
        id="심평원_ch_000001",
        text="Q2333 식도조루술 1,452.18점",
        metadata={"doc_short": "심평원", "page_start": 531},
    )

    system, user = build_quick_code_prompt("식도조루술", [chunk], include_summary=True, include_coverage=False)

    assert "[코드]" in system
    assert "[시술명] 식도조루술" in user
    assert "[산정지침 요약] 줄 추가." in user
    assert "[보상] 줄 추가" not in user
    assert "[컨텍스트 1: 심평원 p.531]" in user


def test_build_quick_code_prompt_adds_coverage_instruction() -> None:
    _, user = build_quick_code_prompt("식도조루술", [], include_summary=False, include_coverage=True)

    assert "제공된 컨텍스트 없음" in user
    assert "[보상] 줄 추가" in user
    assert "[산정지침 요약] 줄 추가." not in user
