import numpy as np

from src.rag.pipeline import RagPipeline, _extract_query_codes
from src.retrieval import Hit


class DummyEmbedder:
    def embed_query(self, text: str):
        return np.asarray([1.0, 0.0], dtype=np.float32)


class DummyVectorStore:
    def __init__(self):
        self.filter_calls = []

    def query(self, query_embedding, top_k: int):
        return [
            Hit(
                id="dense",
                score=0.9,
                document="AA157 재진 진찰료 관련 문장",
                metadata={"page_start": 88, "page_end": 88, "section": "제1절 진찰료"},
            )
        ]

    def query_with_filter(self, query_embedding, filter_codes: list[str], top_k: int, prefer_non_table: bool = False):
        self.filter_calls.append((filter_codes, top_k, prefer_non_table))
        return [
            Hit(
                id="code",
                score=0.95,
                document="AA157 상급종합병원 초진 진찰료 255.79점",
                metadata={"page_start": 101, "page_end": 101, "section": "제1절 진찰료", "codes": ["AA157"]},
            )
        ]


class DummyBM25:
    def query(self, text: str, top_k: int):
        return [
            Hit(
                id="dense",
                score=3.0,
                document="AA157 재진 진찰료 관련 문장",
                metadata={"page_start": 88, "page_end": 88, "section": "제1절 진찰료"},
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
    assert result.chunks[0].id == "dense"
    assert result.timing["total_ms"] >= 0


def test_extract_query_codes_preserves_order_and_deduplicates() -> None:
    codes = _extract_query_codes("AA157과 N39.3, AA157 및 q2333을 확인")

    assert codes == ["AA157", "N39.3", "Q2333"]


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

    hits = pipeline.retrieve_hits("AA157은 무엇인가요?", top_k=8)

    assert vector_store.filter_calls == [(["AA157"], 6, False)]
    assert any(hit.id == "code" for hit in hits)


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

    hits = pipeline.retrieve_hits("AA157은 무엇인가요?", top_k=1)

    assert reranker.calls
    assert reranker.calls[0][2] == 1
    assert len(reranker.calls[0][1]) == 2
    assert len(hits) == 1


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
