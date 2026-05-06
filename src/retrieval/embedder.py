"""문서와 질의 임베딩 래퍼."""

from __future__ import annotations

import numpy as np


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class Embedder:
    """SentenceTransformer 기반 임베더."""

    def __init__(self, model_name: str = "BAAI/bge-m3", allow_remote_download: bool = False):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise RuntimeError("sentence-transformers가 설치되어 있지 않습니다.") from exc

        self.model_name = model_name
        self.allow_remote_download = allow_remote_download
        local_files_only = not allow_remote_download

        try:
            self.model = SentenceTransformer(model_name, local_files_only=local_files_only)
        except TypeError:
            try:
                self.model = SentenceTransformer(model_name)
            except Exception as fallback_exc:
                raise self._load_error(model_name, allow_remote_download) from fallback_exc
        except Exception as exc:
            raise self._load_error(model_name, allow_remote_download) from exc

    @staticmethod
    def _load_error(model_name: str, allow_remote_download: bool) -> RuntimeError:
        if allow_remote_download:
            return RuntimeError(
                f"임베딩 모델을 HuggingFace에서 다운로드하거나 로드할 수 없습니다: {model_name}. "
                "Streamlit Cloud의 네트워크, 메모리 한도, Python 버전, HuggingFace 접근 권한을 확인하세요."
            )
        return RuntimeError(
            f"임베딩 모델을 로컬 캐시에서 로드할 수 없습니다: {model_name}. "
            "README의 사전 단계에 따라 HuggingFace 캐시에 모델을 먼저 내려받으세요. "
            "클라우드에서 원격 다운로드를 허용하려면 HF_MODEL_DOWNLOAD=true를 설정하세요."
        )

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
