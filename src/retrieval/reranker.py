"""BGE reranker wrapper."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src import config
from src.retrieval import Hit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RerankResult:
    """One reranker-scored hit."""

    hit: Hit
    score: float
    rank: int


class Reranker:
    """BGE-reranker-v2-m3 based cross-encoder reranker."""

    DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"

    def __init__(self, model_name: str | None = None, enabled: bool = True, offline_mode: bool | None = None):
        self.enabled = False
        self.model = None
        if not enabled:
            return

        selected_model = model_name or config.RERANKER_MODEL or self.DEFAULT_MODEL
        selected_offline = config.OFFLINE_MODE if offline_mode is None else offline_mode

        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            logger.warning("sentence-transformers 미설치 - reranker 비활성화")
            return

        try:
            logger.info("Reranker 로딩: %s", selected_model)
            try:
                self.model = CrossEncoder(selected_model, max_length=512, local_files_only=True)
            except (OSError, ValueError) as exc:
                if selected_offline:
                    raise RuntimeError(
                        f"OFFLINE_MODE=true에서 reranker를 로컬로 로드할 수 없습니다: {selected_model}"
                    ) from exc
                logger.warning(
                    "Reranker 로컬 캐시 없음 - HuggingFace에서 다운로드합니다: %s. "
                    "완전 오프라인 환경에서는 RERANKER_MODEL을 로컬 경로로 지정하세요.",
                    selected_model,
                )
                self.model = CrossEncoder(selected_model, max_length=512)
        except Exception as exc:  # pragma: no cover - model cache/environment dependent
            logger.warning("Reranker 로딩 실패 - reranker 비활성화: %s", exc)
            return

        self.enabled = True
        logger.info("Reranker 로딩 완료")

    def rerank(self, question: str, hits: list[Hit], top_k: int) -> list[Hit]:
        """Rerank hits and return the top_k results."""

        return [result.hit for result in self.rerank_with_scores(question, hits, top_k)]

    def rerank_with_scores(self, question: str, hits: list[Hit], top_k: int) -> list[RerankResult]:
        """Rerank hits and return hits with cross-encoder scores."""

        if not self.enabled or self.model is None or not hits:
            return [
                RerankResult(hit=hit, score=float(hit.score), rank=index + 1)
                for index, hit in enumerate(hits[:top_k])
            ]

        pairs = [(question, hit.document) for hit in hits]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(hits, scores), key=lambda item: item[1], reverse=True)
        return [
            RerankResult(hit=hit, score=float(score), rank=index + 1)
            for index, (hit, score) in enumerate(ranked[:top_k])
        ]


def build_reranker(enabled: bool = True) -> Reranker | None:
    """Create a reranker according to config."""

    if not enabled:
        return None
    reranker = Reranker(model_name=config.RERANKER_MODEL, enabled=True)
    return reranker if reranker.enabled else None
