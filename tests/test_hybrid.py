from src.retrieval import Hit
from src.retrieval.hybrid import rrf_fuse


def test_rrf_fuse_sums_duplicate_ids_and_orders() -> None:
    dense = [
        Hit(id="a", score=0.9, document="dense a", metadata={"page_start": 1}),
        Hit(id="b", score=0.8, document="dense b", metadata={"page_start": 2}),
    ]
    bm25 = [
        Hit(id="b", score=10.0, document="bm25 b", metadata={"page_start": 2}),
        Hit(id="c", score=9.0, document="bm25 c", metadata={"page_start": 3}),
    ]

    fused = rrf_fuse(dense, bm25, top_k=3, rrf_k=60)

    assert [hit.id for hit in fused] == ["b", "a", "c"]
    assert fused[0].document == "dense b"
    assert fused[0].score > fused[1].score
