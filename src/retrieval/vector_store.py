"""ChromaDB 영속 벡터 저장소 래퍼."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from src.retrieval import Hit


def _encode_metadata(metadata: dict) -> dict:
    encoded = dict(metadata)
    codes = encoded.get("codes")
    if isinstance(codes, list):
        encoded["codes"] = ",".join(str(code) for code in codes)
    return {key: value for key, value in encoded.items() if value is not None}


def _decode_metadata(metadata: dict | None) -> dict:
    decoded = dict(metadata or {})
    codes = decoded.get("codes", "")
    if isinstance(codes, str):
        decoded["codes"] = [code for code in codes.split(",") if code]
    return decoded


class VectorStore:
    """ChromaDB PersistentClient를 사용하는 벡터 저장소."""

    def __init__(self, persist_dir: Path, collection_name: str = "insurance"):
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise RuntimeError("chromadb가 설치되어 있지 않습니다.") from exc

        persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(
        self,
        ids: list[str],
        embeddings: np.ndarray,
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        """문서, 메타데이터, 임베딩을 Chroma에 저장한다."""

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings.tolist(),
            metadatas=[_encode_metadata(metadata) for metadata in metadatas],
            documents=documents,
        )

    def query(self, query_embedding: np.ndarray, top_k: int) -> list[Hit]:
        """질의 임베딩으로 상위 검색 결과를 반환한다."""

        embedding = np.asarray(query_embedding, dtype=np.float32)
        if embedding.ndim == 1:
            embedding = embedding.reshape(1, -1)

        result: dict[str, Any] = self.collection.query(
            query_embeddings=embedding.tolist(),
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        hits: list[Hit] = []
        for index, hit_id in enumerate(ids):
            distance = float(distances[index]) if index < len(distances) else 0.0
            score = 1.0 / (1.0 + max(distance, 0.0))
            hits.append(
                Hit(
                    id=hit_id,
                    score=score,
                    document=documents[index] if index < len(documents) else "",
                    metadata=_decode_metadata(metadatas[index] if index < len(metadatas) else {}),
                )
            )
        return hits
