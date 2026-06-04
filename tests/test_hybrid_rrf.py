from src.retrieval import Hit
from src.retrieval.hybrid import rrf_fuse


def _hit(hit_id: str) -> Hit:
    return Hit(id=hit_id, score=1.0, document=hit_id, metadata={})


def test_rrf_fuse_keeps_equal_weights_by_default() -> None:
    dense_hits = [_hit("dense-only")]
    bm25_hits = [_hit("bm25-only")]

    fused = rrf_fuse(dense_hits, bm25_hits, top_k=2, rrf_k=60)

    assert [hit.id for hit in fused] == ["dense-only", "bm25-only"]


def test_rrf_fuse_can_prioritize_bm25_for_exact_lookup() -> None:
    dense_hits = [_hit("dense-only")]
    bm25_hits = [_hit("bm25-only")]

    fused = rrf_fuse(
        dense_hits,
        bm25_hits,
        top_k=2,
        rrf_k=60,
        dense_weight=0.15,
        bm25_weight=0.85,
    )

    assert fused[0].id == "bm25-only"
    assert fused[0].score > fused[1].score


def test_rrf_fuse_ignores_zero_weight_source() -> None:
    dense_hits = [_hit("dense-only")]
    bm25_hits = [_hit("bm25-only")]

    fused = rrf_fuse(dense_hits, bm25_hits, top_k=2, dense_weight=0.0, bm25_weight=1.0)

    assert [hit.id for hit in fused] == ["bm25-only"]
