import numpy as np

from src.rag.pipeline import RagPipeline
from src.retrieval import Hit


class DummyEmbedder:
    def embed_query(self, text: str):
        return np.asarray([1.0, 0.0], dtype=np.float32)


class DummyVectorStore:
    def query(self, query_embedding, top_k: int):
        return [
            Hit(
                id="dense",
                score=0.9,
                document="AA157 재진 진찰료 관련 문장",
                metadata={"page_start": 88, "page_end": 88, "section": "제1절 진찰료"},
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

    def generate(self, prompt: str, system: str = "", temperature: float = 0.2, num_ctx: int = 8192) -> str:
        self.prompt = prompt
        self.system = system
        return "재진 진찰료 답변입니다. [출처: 제1절 진찰료, p.88]"


def test_pipeline_builds_prompt_and_returns_sources() -> None:
    llm = DummyLLM()
    pipeline = RagPipeline(DummyEmbedder(), DummyVectorStore(), DummyBM25(), llm, top_k_final=8)

    result = pipeline.answer("AA157은 무엇인가요?")

    assert "AA157은 무엇인가요?" in llm.prompt
    assert "[컨텍스트 1]" in llm.prompt
    assert result.answer.startswith("재진 진찰료")
    assert result.chunks[0].id == "dense"
    assert result.timing["total_ms"] >= 0


def test_context_label_backward_compat() -> None:
    """doc_name 없는 구 메타데이터도 context label 생성이 가능하다."""

    from src.llm.prompt import _context_label

    old_meta = {"page_start": 101, "page_end": 101, "volume": "제1편", "section": "재진"}
    label = _context_label(old_meta)

    assert "p.101" in label
    assert "제1편" in label
