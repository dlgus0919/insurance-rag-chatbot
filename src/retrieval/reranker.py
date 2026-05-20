"""BGE reranker wrapper."""

from __future__ import annotations

import logging

from src import config
from src.retrieval import Hit

logger = logging.getLogger(__name__)


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

        if not self.enabled or self.model is None or not hits:
            return hits[:top_k]

        pairs = [(question, hit.document) for hit in hits]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(hits, scores), key=lambda item: item[1], reverse=True)
        return [hit for hit, _ in ranked[:top_k]]


def build_reranker(enabled: bool = True) -> Reranker | None:
    """Create a reranker according to config."""

    if not enabled:
        return None
    reranker = Reranker(model_name=config.RERANKER_MODEL, enabled=True)
    return reranker if reranker.enabled else None
