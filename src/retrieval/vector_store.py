"""ChromaDB 영속 벡터 저장소 래퍼."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import numpy as np

from src.retrieval import Hit

DEFAULT_UPSERT_BATCH_SIZE = 1000


def _encode_metadata(metadata: dict) -> dict:
    encoded = dict(metadata)
    for field in ("codes", "linked_std_cds"):
        value = encoded.get(field)
        if isinstance(value, list):
            encoded[field] = ",".join(str(item) for item in value)
    bbox = encoded.get("bbox")
    if isinstance(bbox, list):
        encoded["bbox"] = json.dumps(bbox, ensure_ascii=False)
    for field in ("is_code_table", "is_own_company"):
        if isinstance(encoded.get(field), bool):
            encoded[field] = "true" if encoded[field] else "false"
    return {key: value for key, value in encoded.items() if value is not None}


def _decode_metadata(metadata: dict | None) -> dict:
    decoded = dict(metadata or {})
    for field in ("codes", "linked_std_cds"):
        value = decoded.get(field, "")
        if isinstance(value, str):
            decoded[field] = [item for item in value.split(",") if item]
    bbox = decoded.get("bbox")
    if isinstance(bbox, str):
        try:
            decoded["bbox"] = json.loads(bbox)
        except json.JSONDecodeError:
            decoded["bbox"] = None
    for field in ("is_code_table", "is_own_company"):
        value = decoded.get(field)
        if isinstance(value, str):
            decoded[field] = value.lower() == "true"
    if "is_code_table" not in decoded:
        decoded["is_code_table"] = False
    return decoded


def _has_code_row(document: str, codes: set[str]) -> bool:
    """코드가 표 행의 핵심 위치에 있는지 확인한다."""

    for code in codes:
        pattern = rf"(^|\n)\s*(?:[가-힣]?-?\d+(?:-\d+)?\s+)?{re.escape(code)}(?![A-Z0-9.])"
        if re.search(pattern, document):
            return True
    return False


def _doc_filter_where(doc_filter: list[str] | None) -> dict | None:
    """Chroma where 절에 사용할 문서 필터를 만든다."""

    if not doc_filter:
        return None
    values = list(dict.fromkeys(doc_filter))
    if not values:
        return None
    return {"doc_short": {"$in": values}}


def _matches_doc_filter(metadata: dict, doc_filter: list[str] | None) -> bool:
    """메타데이터가 선택 문서 필터에 포함되는지 확인한다."""

    return not doc_filter or metadata.get("doc_short") in set(doc_filter)


class VectorStore:
    """ChromaDB PersistentClient를 사용하는 벡터 저장소."""

    def __init__(
        self,
        persist_dir: Path,
        collection_name: str = "insurance",
        reset: bool = False,
        upsert_batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
    ):
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise RuntimeError("chromadb가 설치되어 있지 않습니다.") from exc

        if upsert_batch_size <= 0:
            raise ValueError("upsert_batch_size must be positive")

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
        self.upsert_batch_size = upsert_batch_size

    def upsert(
        self,
        ids: list[str],
        embeddings: np.ndarray,
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        """문서, 메타데이터, 임베딩을 Chroma에 저장한다."""

        if not ids:
            self._all_entries_cache = None
            return
        if len(ids) != len(metadatas) or len(ids) != len(documents) or len(ids) != len(embeddings):
            raise ValueError("ids, embeddings, metadatas, and documents must have the same length")

        batch_size = int(getattr(self, "upsert_batch_size", DEFAULT_UPSERT_BATCH_SIZE))
        if batch_size <= 0:
            raise ValueError("upsert_batch_size must be positive")

        encoded_metadatas = [_encode_metadata(metadata) for metadata in metadatas]
        for start in range(0, len(ids), batch_size):
            end = min(start + batch_size, len(ids))
            self.collection.upsert(
                ids=ids[start:end],
                embeddings=embeddings[start:end].tolist(),
                metadatas=encoded_metadatas[start:end],
                documents=documents[start:end],
            )
        self._all_entries_cache = None

    def query(self, query_embedding: np.ndarray, top_k: int, doc_filter: list[str] | None = None) -> list[Hit]:
        """질의 임베딩으로 상위 검색 결과를 반환한다."""

        embedding = np.asarray(query_embedding, dtype=np.float32)
        if embedding.ndim == 1:
            embedding = embedding.reshape(1, -1)

        where = _doc_filter_where(doc_filter)
        query_kwargs: dict[str, Any] = {
            "query_embeddings": embedding.tolist(),
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where is not None:
            query_kwargs["where"] = where

        result: dict[str, Any] = self.collection.query(**query_kwargs)
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
        doc_filter: list[str] | None = None,
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
            if not _matches_doc_filter(metadata, doc_filter):
                continue
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

    def get_by_ids(self, ids: list[str]) -> list[Hit]:
        """주어진 chunk ID 목록으로 문서를 조회하여 Hit 목록으로 반환한다."""
        if not ids:
            return []

        def _get_fallback_ids(chunk_id: str) -> list[str]:
            fallbacks = []
            if chunk_id.startswith("v1_"):
                suffix = chunk_id[3:]
                fallbacks.append(f"v2_{suffix}")
                fallbacks.append(suffix)
            elif chunk_id.startswith("v2_"):
                suffix = chunk_id[3:]
                fallbacks.append(f"v1_{suffix}")
                fallbacks.append(suffix)
            else:
                fallbacks.append(f"v1_{chunk_id}")
                fallbacks.append(f"v2_{chunk_id}")
            return fallbacks

        all_candidates = []
        id_to_fallbacks = {}
        for chunk_id in ids:
            fallbacks = _get_fallback_ids(chunk_id)
            id_to_fallbacks[chunk_id] = fallbacks
            all_candidates.append(chunk_id)
            all_candidates.extend(fallbacks)

        seen = set()
        unique_candidates = []
        for cid in all_candidates:
            if cid not in seen:
                seen.add(cid)
                unique_candidates.append(cid)

        result = self.collection.get(ids=unique_candidates, include=["documents", "metadatas"])
        r_ids = result.get("ids", [])
        r_documents = result.get("documents", [])
        r_metadatas = result.get("metadatas", [])

        db_map = {}
        for index, hit_id in enumerate(r_ids):
            db_map[hit_id] = {
                "document": r_documents[index] if index < len(r_documents) else "",
                "metadata": _decode_metadata(r_metadatas[index] if index < len(r_metadatas) else {})
            }

        hits: list[Hit] = []
        for chunk_id in ids:
            target_id = None
            if chunk_id in db_map:
                target_id = chunk_id
            else:
                for fb in id_to_fallbacks.get(chunk_id, []):
                    if fb in db_map:
                        target_id = fb
                        break

            if target_id is not None:
                data = db_map[target_id]
                hits.append(
                    Hit(
                        id=chunk_id,
                        score=1.0,
                        document=data["document"],
                        metadata=data["metadata"],
                    )
                )
        return hits
