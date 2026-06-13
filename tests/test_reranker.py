from src.retrieval import Hit
from src.retrieval.reranker import Reranker, build_reranker


def test_disabled_reranker_returns_top_k_without_model() -> None:
    reranker = Reranker(enabled=False)
    hits = [
        Hit(id="a", score=0.1, document="A", metadata={}),
        Hit(id="b", score=0.2, document="B", metadata={}),
    ]

    assert reranker.rerank("질문", hits, top_k=1) == [hits[0]]
    scored = reranker.rerank_with_scores("질문", hits, top_k=1)
    assert scored[0].hit == hits[0]
    assert scored[0].score == 0.1
    assert scored[0].rank == 1


def test_reranker_with_scores_orders_by_model_score() -> None:
    class FakeModel:
        def predict(self, pairs):
            assert pairs == [("질문", "A"), ("질문", "B")]
            return [0.2, 0.9]

    reranker = Reranker(enabled=False)
    reranker.enabled = True
    reranker.model = FakeModel()
    hits = [
        Hit(id="a", score=0.1, document="A", metadata={}),
        Hit(id="b", score=0.2, document="B", metadata={}),
    ]

    scored = reranker.rerank_with_scores("질문", hits, top_k=2)

    assert [result.hit.id for result in scored] == ["b", "a"]
    assert [result.score for result in scored] == [0.9, 0.2]
    assert [result.rank for result in scored] == [1, 2]
    assert reranker.rerank("질문", hits, top_k=1) == [hits[1]]


def test_build_reranker_disabled_returns_none() -> None:
    assert build_reranker(enabled=False) is None
