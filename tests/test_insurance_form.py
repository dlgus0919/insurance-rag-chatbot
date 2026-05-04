import pytest

from src.parser.chunker import Chunk
from src.rag.insurance_form import (
    INSURANCE_DISCLAIMER,
    InsuranceFormInput,
    build_form_prompt,
    build_form_query,
    generate_insurance_form_answer,
    merge_insurance_doc_filter,
    retrieve_insurance_form_chunks,
)
from src.retrieval import Hit


class FakeLLM:
    def __init__(self, answer: str = "약관 기준 답변입니다."):
        self.answer = answer
        self.calls = []

    def generate(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        self.calls.append((prompt, system, temperature))
        return self.answer


class FakePipeline:
    def __init__(self):
        self.llm = FakeLLM()
        self.retrieve_calls = []

    def retrieve_hits(self, question: str, top_k: int | None = None, doc_filter: list[str] | None = None):
        self.retrieve_calls.append((question, top_k, doc_filter))
        return [
            Hit(
                id="약관_ch_000001",
                score=1.0,
                document="N39.3 요실금은 보상하지 않는 사항입니다.",
                metadata={"doc_short": "약관", "chapter": "제3조", "page_start": 38, "page_end": 38},
            )
        ]


def test_build_form_query_for_three_modes() -> None:
    coverage = InsuranceFormInput(
        mode="coverage_judgment",
        primary="N39.3",
        coverage_topics=["질병급여", "3대비급여"],
        situation_note="입원 치료",
    )
    clause = InsuranceFormInput(mode="clause_lookup", primary="보상하지 않는 사항", article_number="3", include_appendix=True)
    keyword = InsuranceFormInput(mode="keyword_search", primary="도수치료")

    assert "N39.3 보상하지 않는 사항" in build_form_query(coverage)
    assert "질병급여" in build_form_query(coverage)
    assert build_form_query(clause) == "보상하지 않는 사항 제3조 별표"
    assert build_form_query(keyword) == "도수치료"


def test_build_form_query_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        build_form_query(InsuranceFormInput(mode="unknown", primary="x"))


def test_build_form_prompt_for_coverage_mode() -> None:
    chunk = Chunk(
        id="약관_ch_000001",
        text="요실금은 보상하지 않습니다.",
        metadata={"doc_short": "약관", "chapter": "제3조", "page_start": 38},
    )
    form = InsuranceFormInput(mode="coverage_judgment", primary="N39.3", coverage_topics=["질병급여"])

    system, user = build_form_prompt(form, [chunk])

    assert "보상가능 여부" in system
    assert "[대상] N39.3" in user
    assert "[보장종목] 질병급여" in user
    assert "[컨텍스트 1: 제3조 / p.38]" in user


def test_build_form_prompt_for_clause_and_keyword_modes() -> None:
    clause = InsuranceFormInput(mode="clause_lookup", primary="보상하지 않는 사항", article_number="3", include_appendix=True)
    keyword = InsuranceFormInput(mode="keyword_search", primary="도수치료")

    clause_system, clause_user = build_form_prompt(clause, [])
    keyword_system, keyword_user = build_form_prompt(keyword, [])

    assert "조문을 정확히 인용" in clause_system
    assert "[조건] 조문번호 제3조, 별표 포함" in clause_user
    assert "시술명·용어" in keyword_system
    assert "[키워드] 도수치료" in keyword_user


def test_retrieve_insurance_form_chunks_forces_policy_filter() -> None:
    pipeline = FakePipeline()
    form = InsuranceFormInput(mode="keyword_search", primary="도수치료")

    chunks, doc_filter = retrieve_insurance_form_chunks(pipeline, form, extra_doc_filter=["심평원", "약관"])

    assert doc_filter == ["약관", "심평원"]
    assert pipeline.retrieve_calls[0][2] == ["약관", "심평원"]
    assert chunks[0].metadata["doc_short"] == "약관"


def test_generate_insurance_form_answer_adds_disclaimer_and_citation() -> None:
    pipeline = FakePipeline()
    chunk = Chunk(
        id="약관_ch_000001",
        text="요실금은 보상하지 않습니다.",
        metadata={"doc_short": "약관", "chapter": "제3조", "page_start": 38, "page_end": 38},
    )
    form = InsuranceFormInput(mode="coverage_judgment", primary="N39.3", coverage_topics=["질병급여"])

    answer = generate_insurance_form_answer(pipeline, form, [chunk], temperature=0.1)

    assert "[출처: 약관, 제3조, p.38]" in answer
    assert answer.endswith(INSURANCE_DISCLAIMER)
    assert pipeline.llm.calls[0][2] == 0.1


def test_merge_insurance_doc_filter_deduplicates() -> None:
    assert merge_insurance_doc_filter(["심평원", "약관", "가이드북"]) == ["약관", "심평원", "가이드북"]
