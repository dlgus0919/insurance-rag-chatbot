import json

import numpy as np

from src.rag.pipeline import (
    DebugInfo,
    RagPipeline,
    _boost_surgery_name_table_rows,
    _expand_retrieval_query,
    _extract_named_code_terms,
    _extract_query_codes,
    _extract_surgery_name_from_query,
    _hits_to_stage,
    _is_low_value_wide_range,
    _prefer_exact_text_hits,
)
from src.retrieval import Hit


class DummyEmbedder:
    def embed_query(self, text: str):
        return np.asarray([1.0, 0.0], dtype=np.float32)


class DummyVectorStore:
    def __init__(self):
        self.filter_calls = []
        self.query_calls = []

    def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
        self.query_calls.append((top_k, doc_filter))
        return [
            Hit(
                id="dense",
                score=0.9,
                document="AA157 재진 진찰료 관련 문장",
                metadata={"doc_short": "심평원", "page_start": 88, "page_end": 88, "section": "제1절 진찰료"},
            )
        ]

    def query_with_filter(
        self,
        query_embedding,
        filter_codes: list[str],
        top_k: int,
        prefer_non_table: bool = True,
        doc_filter: list[str] | None = None,
    ):
        self.filter_calls.append((filter_codes, top_k, prefer_non_table, doc_filter))
        return [
            Hit(
                id="code",
                score=0.95,
                document="AA157 상급종합병원 초진 진찰료 255.79점",
                metadata={
                    "doc_short": "심평원",
                    "page_start": 101,
                    "page_end": 101,
                    "section": "제1절 진찰료",
                    "codes": ["AA157"],
                },
            )
        ]


class DummyBM25:
    def query(self, text: str, top_k: int):
        return [
            Hit(
                id="dense",
                score=3.0,
                document="AA157 재진 진찰료 관련 문장",
                metadata={"doc_short": "심평원", "page_start": 88, "page_end": 88, "section": "제1절 진찰료"},
            ),
            Hit(
                id="policy",
                score=2.0,
                document="약관 청크",
                metadata={"doc_short": "약관", "page_start": 38, "page_end": 38},
            )
        ]


class DummyLLM:
    def __init__(self):
        self.prompt = ""
        self.system = ""

    def generate(self, prompt: str, system: str = "", temperature: float = 0.2, num_ctx: int | None = None) -> str:
        self.prompt = prompt
        self.system = system
        return "재진 진찰료 답변입니다. [출처: 제1절 진찰료, p.88]"


class DummyReranker:
    enabled = True

    def __init__(self):
        self.calls = []

    def rerank(self, question: str, hits: list[Hit], top_k: int) -> list[Hit]:
        self.calls.append((question, [hit.id for hit in hits], top_k))
        return list(reversed(hits))[:top_k]


def test_pipeline_builds_prompt_and_returns_sources() -> None:
    llm = DummyLLM()
    pipeline = RagPipeline(DummyEmbedder(), DummyVectorStore(), DummyBM25(), llm, top_k_final=8, reranker_enabled=False)

    result = pipeline.answer("AA157은 무엇인가요?")

    assert "AA157은 무엇인가요?" in llm.prompt
    assert "[컨텍스트 1:" in llm.prompt
    assert result.answer.startswith("재진 진찰료")
    assert result.chunks[0].id == "code"
    assert result.timing["total_ms"] >= 0


def test_extract_query_codes_preserves_order_and_deduplicates() -> None:
    codes = _extract_query_codes("AA157과 N39.3, AA157 및 q2333을 확인")

    assert codes == ["AA157", "N39.3", "Q2333"]


def test_expand_retrieval_query_for_three_major_non_covered_items() -> None:
    expanded = _expand_retrieval_query("실손의료보험 약관에서 3대비급여에 해당하는 항목은 무엇인가요?")

    assert "도수치료" in expanded
    assert "자기공명영상진단" in expanded


def test_expand_retrieval_query_for_traffic_accident() -> None:
    expanded = _expand_retrieval_query("보험 가입 후 3일째 교통사고로 입원했습니다.")

    assert "상해급여" in expanded
    assert "자동차보험" in expanded
    assert "보장개시일" in expanded


def test_expand_retrieval_query_for_motorcycle() -> None:
    expanded = _expand_retrieval_query("이륜자동차를 운전하다가 사고가 났습니다.")

    assert "이륜자동차 부담보 특별약관" in expanded
    assert "알릴 의무" in expanded


def test_expand_retrieval_query_for_drunk_injury() -> None:
    expanded = _expand_retrieval_query("술을 마신 상태에서 넘어져 상해를 입었습니다.")

    assert "면책" in expanded
    assert "중대한 과실" in expanded


def test_extract_named_code_terms() -> None:
    assert _extract_named_code_terms("식도조루술의 코드를 알려줘.") == ["식도조루술"]


def test_extract_surgery_name_from_query_surgery_grade() -> None:
    assert _extract_surgery_name_from_query("사지골 사지관절 가관절수술의 수술종수는?") == "사지골 사지관절 가관절수술"
    assert _extract_surgery_name_from_query("체외금속고정술의 수술종수는?") == "체외금속고정술"
    assert _extract_surgery_name_from_query("제허니아 근본수술의 1-3종·1-5종·신1-5종 수술종수는?") == "제허니아 근본수술"
    assert _extract_surgery_name_from_query("결장경하 종양수술은 어떤 도구를 사용하는가?") == "결장경하 종양수술"


def test_extract_surgery_name_from_query_non_surgery() -> None:
    assert _extract_surgery_name_from_query("두 눈이 멀었을 때 장해 지급률은?") is None
    assert _extract_surgery_name_from_query("계약 전 알릴 의무를 위반한 경우 어떤 불이익이 있는가?") is None
    assert _extract_surgery_name_from_query("척추에 심한 운동장해가 남은 경우 지급률은?") is None


def test_boost_surgery_name_table_rows_matched_first() -> None:
    matched_hit = Hit(
        id="p64",
        score=0.7,
        document="사지골 사지관절 | 수술해설 | 1 | 2 | 2",
        metadata={
            "doc_short": "실무가이드",
            "page_start": 64,
            "table_json": json.dumps(
                {
                    "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
                    "rows": [
                        {
                            "수술명": "사지골 사지관절 가관절수술",
                            "수술해설": "...",
                            "1-3종": "1",
                            "1-5종": "2",
                            "신1-5종": "2",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        },
    )
    unmatched_hit = Hit(
        id="p63",
        score=0.9,
        document="사지골 관련 다른 표",
        metadata={"doc_short": "실무가이드", "page_start": 63, "table_json": "{}"},
    )

    result = _boost_surgery_name_table_rows(
        [unmatched_hit, matched_hit],
        surgery_name="사지골 사지관절 가관절수술",
    )

    assert result[0].id == "p64"
    assert result[1].id == "p63"


def test_boost_surgery_name_table_rows_no_match_preserves_order() -> None:
    hits = [
        Hit(id="a", score=0.9, document="text", metadata={"table_json": "{}"}),
        Hit(id="b", score=0.8, document="text", metadata={"table_json": "{}"}),
    ]

    result = _boost_surgery_name_table_rows(hits, surgery_name="없는수술명")

    assert [hit.id for hit in result] == ["a", "b"]


def test_prefer_exact_text_hits() -> None:
    hits = [
        Hit(id="generic", score=1.0, document="분류번호 및 코드 표", metadata={}),
        Hit(id="exact", score=0.8, document="Q2333 식도조루술", metadata={}),
    ]

    ordered = _prefer_exact_text_hits(hits, ["식도조루술"])

    assert [hit.id for hit in ordered] == ["exact", "generic"]


def test_code_query_uses_filtered_dense_hits() -> None:
    vector_store = DummyVectorStore()
    pipeline = RagPipeline(
        DummyEmbedder(),
        vector_store,
        DummyBM25(),
        DummyLLM(),
        top_k_dense=12,
        top_k_final=8,
        reranker_enabled=False,
    )

    hits, _ = pipeline.retrieve_hits("AA157은 무엇인가요?", top_k=8)

    assert vector_store.filter_calls == [(["AA157"], 6, True, None)]
    assert hits[0].id == "code"


def test_doc_filter_flows_to_vector_store_and_filters_bm25() -> None:
    vector_store = DummyVectorStore()
    pipeline = RagPipeline(
        DummyEmbedder(),
        vector_store,
        DummyBM25(),
        DummyLLM(),
        top_k_dense=12,
        top_k_final=8,
        reranker_enabled=False,
    )

    hits, _ = pipeline.retrieve_hits("AA157은 무엇인가요?", top_k=8, doc_filter=["심평원"])

    assert vector_store.filter_calls == [(["AA157"], 6, True, ["심평원"])]
    assert vector_store.query_calls == [(6, ["심평원"])]
    assert all(hit.metadata.get("doc_short") == "심평원" for hit in hits)


def test_reranker_receives_expanded_rrf_pool() -> None:
    reranker = DummyReranker()
    pipeline = RagPipeline(
        DummyEmbedder(),
        DummyVectorStore(),
        DummyBM25(),
        DummyLLM(),
        top_k_final=1,
        reranker=reranker,
    )

    hits, _ = pipeline.retrieve_hits("AA157은 무엇인가요?", top_k=1)

    assert reranker.calls
    assert reranker.calls[0][2] == 1
    assert len(reranker.calls[0][1]) == 2
    assert len(hits) == 1


def test_low_value_wide_range_detection() -> None:
    hit = Hit(
        id="toc",
        score=1.0,
        document="목차성 짧은 청크",
        metadata={"page_start": 8, "page_end": 31, "char_count": 168},
    )

    assert _is_low_value_wide_range(hit) is True


def test_retrieve_hits_can_return_debug_info() -> None:
    pipeline = RagPipeline(
        DummyEmbedder(),
        DummyVectorStore(),
        DummyBM25(),
        DummyLLM(),
        top_k_final=2,
        reranker_enabled=False,
    )

    hits, debug = pipeline.retrieve_hits("AA157은 무엇인가요?", top_k=2, return_debug=True)

    assert len(hits) == 2
    assert isinstance(debug, DebugInfo)
    assert debug.dense_hits[0].chunk_id == "code"
    assert debug.bm25_hits[0].chunk_id == "dense"
    assert debug.rrf_hits
    assert debug.final_hits


def test_hits_to_stage_rounds_score_and_preview() -> None:
    hit = Hit(id="a", score=1.23456, document="가" * 120, metadata={"doc_short": "약관", "page_start": 3})

    stage_hits = _hits_to_stage([hit])

    assert stage_hits[0].score == 1.2346
    assert stage_hits[0].doc_short == "약관"
    assert len(stage_hits[0].text_preview) == 100


def test_context_label_backward_compat() -> None:
    """doc_name 없는 구 메타데이터도 context label 생성이 가능하다."""

    from src.llm.prompt import _context_label

    old_meta = {"page_start": 101, "page_end": 101, "volume": "제1편", "section": "재진"}
    label = _context_label(old_meta)

    assert "p.101" in label
    assert "제1편" in label


def test_context_label_prefers_doc_short_in_prompt() -> None:
    """컨텍스트 라벨은 문서 축약명을 앞에 표시한다."""

    from src.llm.prompt import build_user_prompt
    from src.parser.chunker import Chunk

    chunk = Chunk(
        id="약관_ch_000001",
        text="N39.3은 보상하지 않습니다.",
        metadata={
            "doc_short": "약관",
            "doc_name": "신한 약관",
            "chapter": "제3조(보장종목별 보상내용)",
            "page_start": 38,
            "page_end": 38,
        },
    )

    prompt = build_user_prompt("N39.3은 보상되나요?", [chunk])

    assert "[컨텍스트 1: [약관] 제3조(보장종목별 보상내용) / p.38]" in prompt


def test_append_retrieved_source_citations_adds_top_pages() -> None:
    """검색 출처를 답변 하단에 보강한다."""

    from src.llm.prompt import append_retrieved_source_citations
    from src.parser.chunker import Chunk

    chunks = [
        Chunk(
            id="심평원_ch_000166",
            text="AA157 (5) 상급종합병원 255.79",
            metadata={"doc_short": "심평원", "section": "제1절 기본진료료", "page_start": 101, "page_end": 101},
        )
    ]

    answer = append_retrieved_source_citations("AA157 답변입니다.", chunks)

    assert "[출처: 심평원, 제1절 기본진료료, p.101]" in answer


def test_append_retrieved_source_citations_skips_existing_citation() -> None:
    """이미 있는 출처 표기는 중복 추가하지 않는다."""

    from src.llm.prompt import append_retrieved_source_citations
    from src.parser.chunker import Chunk

    chunk = Chunk(
        id="심평원_ch_000166",
        text="AA157 (5) 상급종합병원 255.79",
        metadata={"doc_short": "심평원", "section": "제1절 기본진료료", "page_start": 101, "page_end": 101},
    )
    citation = "[출처: 심평원, 제1절 기본진료료, p.101]"

    answer = append_retrieved_source_citations(f"AA157 답변입니다.\n{citation}", [chunk])

    assert answer.count(citation) == 1
