"""문서와 질의 임베딩 래퍼."""

from __future__ import annotations

import numpy as np


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class Embedder:
    """SentenceTransformer 기반 임베더."""

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise RuntimeError("sentence-transformers가 설치되어 있지 않습니다.") from exc

        try:
            self.model = SentenceTransformer(model_name, local_files_only=True)
        except TypeError:
            self.model = SentenceTransformer(model_name)
        except Exception as exc:
            raise RuntimeError(
                f"임베딩 모델을 로드할 수 없습니다: {model_name}. "
                "README의 사전 단계에 따라 HuggingFace 캐시에 모델을 먼저 내려받으세요."
            ) from exc

    def embed_documents(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        """문서 목록을 L2 정규화된 임베딩 배열로 변환한다."""

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        return _l2_normalize(np.asarray(embeddings, dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        """질문 한 개를 L2 정규화된 임베딩 벡터로 변환한다."""

        embedding = self.model.encode([text], normalize_embeddings=True)
        return _l2_normalize(np.asarray(embedding, dtype=np.float32))[0]
