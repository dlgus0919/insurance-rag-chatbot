"""ChromaDB 영속 벡터 저장소 래퍼."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import numpy as np

from src.retrieval import Hit


def _encode_metadata(metadata: dict) -> dict:
    encoded = dict(metadata)
    codes = encoded.get("codes")
    if isinstance(codes, list):
        encoded["codes"] = ",".join(str(code) for code in codes)
    if isinstance(encoded.get("is_code_table"), bool):
        encoded["is_code_table"] = "true" if encoded["is_code_table"] else "false"
    return {key: value for key, value in encoded.items() if value is not None}


def _decode_metadata(metadata: dict | None) -> dict:
    decoded = dict(metadata or {})
    codes = decoded.get("codes", "")
    if isinstance(codes, str):
        decoded["codes"] = [code for code in codes.split(",") if code]
    is_code_table = decoded.get("is_code_table")
    if isinstance(is_code_table, str):
        decoded["is_code_table"] = is_code_table.lower() == "true"
    elif "is_code_table" not in decoded:
        decoded["is_code_table"] = False
    return decoded


def _has_code_row(document: str, codes: set[str]) -> bool:
    """코드가 표 행의 핵심 위치에 있는지 확인한다."""

    for code in codes:
        pattern = rf"(^|\n)\s*(?:[가-힣]?-?\d+(?:-\d+)?\s+)?{re.escape(code)}(?![A-Z0-9.])"
        if re.search(pattern, document):
            return True
    return False


class VectorStore:
    """ChromaDB PersistentClient를 사용하는 벡터 저장소."""

    def __init__(self, persist_dir: Path, collection_name: str = "insurance", reset: bool = False):
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise RuntimeError("chromadb가 설치되어 있지 않습니다.") from exc

        persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        if reset:
            try:
                self.client.delete_collection(collection_name)
            except Exception:
                pass
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._all_entries_cache: dict[str, Any] | None = None

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
        self._all_entries_cache = None

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

    def _all_entries(self) -> dict[str, Any]:
        """코드 필터링용 전체 컬렉션 데이터를 캐시해 반환한다."""

        if self._all_entries_cache is None:
            self._all_entries_cache = self.collection.get(include=["documents", "metadatas", "embeddings"])
        return self._all_entries_cache

    def query_with_filter(
        self,
        query_embedding: np.ndarray,
        filter_codes: list[str],
        top_k: int,
        prefer_non_table: bool = True,
    ) -> list[Hit]:
        """codes 메타데이터가 질의 코드와 정확히 일치하는 청크만 검색한다."""

        if not filter_codes or top_k <= 0:
            return []

        try:
            entries = self._all_entries()
        except Exception:
            return []

        ids = entries.get("ids", [])
        documents = entries.get("documents", [])
        metadatas = entries.get("metadatas", [])
        embeddings = entries.get("embeddings", [])
        if not ids or embeddings is None:
            return []

        wanted_codes = {code.upper() for code in filter_codes}
        query = np.asarray(query_embedding, dtype=np.float32)
        if query.ndim > 1:
            query = query.reshape(-1)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []
        query = query / query_norm

        candidates: list[tuple[int, dict]] = []
        fallback_candidates: list[tuple[int, dict]] = []
        for index, raw_meta in enumerate(metadatas):
            metadata = _decode_metadata(raw_meta)
            codes = {str(code).upper() for code in metadata.get("codes", [])}
            if not codes.intersection(wanted_codes):
                continue
            fallback_candidates.append((index, metadata))
            if not prefer_non_table or metadata.get("is_code_table") is not True:
                candidates.append((index, metadata))

        selected = candidates or fallback_candidates
        if not selected:
            return []

        scored_hits: list[Hit] = []
        for index, metadata in selected:
            vector = np.asarray(embeddings[index], dtype=np.float32)
            vector_norm = np.linalg.norm(vector)
            if vector_norm == 0:
                score = 0.0
            else:
                score = float(np.dot(query, vector / vector_norm))
            if _has_code_row(documents[index] if index < len(documents) else "", wanted_codes):
                score += 0.25
            scored_hits.append(
                Hit(
                    id=ids[index],
                    score=score,
                    document=documents[index] if index < len(documents) else "",
                    metadata=metadata,
                )
            )

        return sorted(scored_hits, key=lambda hit: hit.score, reverse=True)[:top_k]
