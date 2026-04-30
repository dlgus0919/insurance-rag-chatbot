from src.retrieval import Hit
from src.retrieval.reranker import Reranker, build_reranker


def test_disabled_reranker_returns_top_k_without_model() -> None:
    reranker = Reranker(enabled=False)
    hits = [
        Hit(id="a", score=0.1, document="A", metadata={}),
        Hit(id="b", score=0.2, document="B", metadata={}),
    ]

    assert reranker.rerank("질문", hits, top_k=1) == [hits[0]]


def test_build_reranker_disabled_returns_none() -> None:
    assert build_reranker(enabled=False) is None
