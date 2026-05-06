"""BGE reranker 래퍼."""

from __future__ import annotations

import logging

from src.retrieval import Hit

logger = logging.getLogger(__name__)


class Reranker:
    """BGE-reranker-v2-m3 기반 크로스인코더 reranker."""

    DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"

    def __init__(self, model_name: str = DEFAULT_MODEL, enabled: bool = True):
        self.enabled = False
        self.model = None
        if not enabled:
            return

        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            logger.warning("sentence-transformers 미설치 - reranker 비활성화")
            return

        try:
            logger.info("Reranker 로딩: %s", model_name)
            try:
                self.model = CrossEncoder(model_name, max_length=512, local_files_only=True)
            except (OSError, ValueError):
                # 캐시 미스 시 한 번만 원격 다운로드 허용 (초기 셋업용 경고 포함)
                logger.warning(
                    "Reranker 로컬 캐시 없음 — HuggingFace에서 다운로드합니다: %s. "
                    "오프라인 환경에서는 먼저 모델을 내려받아야 합니다.",
                    model_name,
                )
                self.model = CrossEncoder(model_name, max_length=512)
        except Exception as exc:  # pragma: no cover - 모델 캐시/환경 의존
            logger.warning("Reranker 로딩 실패 - reranker 비활성화: %s", exc)
            return

        self.enabled = True
        logger.info("Reranker 로딩 완료")

    def rerank(self, question: str, hits: list[Hit], top_k: int) -> list[Hit]:
        """검색 후보를 rerank해 상위 top_k개를 반환한다."""

        if not self.enabled or self.model is None or not hits:
            return hits[:top_k]

        pairs = [(question, hit.document) for hit in hits]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(hits, scores), key=lambda item: item[1], reverse=True)
        return [hit for hit, _ in ranked[:top_k]]


def build_reranker(enabled: bool = True) -> Reranker | None:
    """설정에 따라 Reranker 인스턴스를 생성한다."""

    if not enabled:
        return None
    reranker = Reranker(enabled=True)
    return reranker if reranker.enabled else None
