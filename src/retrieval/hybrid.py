"""Dense/BM25 검색 결과 융합."""

from __future__ import annotations

from src.retrieval import Hit


def rrf_fuse(
    dense_hits: list[Hit],
    bm25_hits: list[Hit],
    top_k: int = 8,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    bm25_weight: float = 1.0,
) -> list[Hit]:
    """
    Reciprocal Rank Fusion으로 두 검색 결과를 합친다.

    score(d) = sum(weight_i / (rrf_k + rank_i(d)))이며 rank는 1부터 시작한다.
    동일 id가 양쪽에 있으면 점수를 합산하고, 문서/메타데이터는 먼저
    발견된 결과를 사용한다.
    """

    fused: dict[str, Hit] = {}

    for hits, source_weight in ((dense_hits, dense_weight), (bm25_hits, bm25_weight)):
        if source_weight <= 0:
            continue
        for rank, hit in enumerate(hits, start=1):
            score = source_weight / (rrf_k + rank)
            if hit.id not in fused:
                fused[hit.id] = Hit(
                    id=hit.id,
                    score=score,
                    document=hit.document,
                    metadata=dict(hit.metadata),
                )
            else:
                fused[hit.id].score += score
                if not fused[hit.id].document and hit.document:
                    fused[hit.id].document = hit.document
                if not fused[hit.id].metadata and hit.metadata:
                    fused[hit.id].metadata = dict(hit.metadata)

    return sorted(fused.values(), key=lambda hit: hit.score, reverse=True)[:top_k]
