"""v2 canonical -> v1 pair 매핑 로더."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from src import config


class PairMappingStore:
    """문서별 v1-v2 매핑 JSONL을 로드해 조회한다."""

    def __init__(self, mapping_dir: Path | None = None):
        self.mapping_dir = mapping_dir or (config.ROOT_DIR / "data" / "mapping")
        self._pairs: dict[str, dict] = {}

    def load_doc(self, doc_short: str) -> int:
        """문서별 매핑 파일을 로드하고 로드 건수를 반환한다."""

        path = self.mapping_dir / f"v1_v2_pairs_{doc_short}.jsonl"
        if not path.exists():
            return 0
        count = 0
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = str(row.get("canonical_chunk_id") or "")
                if not key:
                    continue
                self._pairs[key] = row
                count += 1
        return count

    def get(self, canonical_chunk_id: str) -> dict | None:
        """canonical(v2) chunk id로 pair 정보를 조회한다."""

        return self._pairs.get(canonical_chunk_id)


def load_chunk_lookup(chunks_path: Path, docs: list[str] | None = None) -> dict[str, dict]:
    """청크 JSONL에서 id -> row 조회 딕셔너리를 로드한다."""

    allowed = set(docs or [])
    use_filter = bool(allowed)
    lookup: dict[str, dict] = {}
    with chunks_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            meta = row.get("metadata", {})
            if use_filter and meta.get("doc_short") not in allowed:
                continue
            lookup[row["id"]] = row
    return lookup


_SOURCE_PROVENANCE_FIELDS = (
    "doc_short",
    "doc_name",
    "pdf_filename",
    "page_start",
    "page_end",
    "chapter",
    "product_type",
    "source_method",
)


def _source_provenance_key(row: dict) -> tuple[str, ...] | None:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return None
    text = re.sub(r"\s+", "", str(row.get("text") or ""))
    if not text:
        return None
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return (text_hash, *(str(metadata.get(field) or "") for field in _SOURCE_PROVENANCE_FIELDS))


def load_source_metadata_lookup(
    canonical_chunks_path: Path,
    indexed_chunks_path: Path | None = None,
) -> dict[str, dict]:
    """Load canonical metadata and conservative aliases for rechunked source IDs."""

    lookup = load_chunk_lookup(canonical_chunks_path)
    if indexed_chunks_path is None or not indexed_chunks_path.exists():
        return lookup
    if indexed_chunks_path.resolve() == canonical_chunks_path.resolve():
        return lookup

    by_provenance: dict[tuple[str, ...], list[dict]] = {}
    for canonical_row in lookup.values():
        key = _source_provenance_key(canonical_row)
        if key is not None:
            by_provenance.setdefault(key, []).append(canonical_row)

    with indexed_chunks_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            indexed_row = json.loads(line)
            key = _source_provenance_key(indexed_row)
            matches = by_provenance.get(key, []) if key is not None else []
            if len(matches) != 1:
                continue
            source_metadata = indexed_row.get("metadata")
            candidate_ids = [indexed_row.get("id")]
            if isinstance(source_metadata, dict):
                candidate_ids.extend(
                    source_metadata.get(field)
                    for field in ("source_chunk_id", "canonical_chunk_id")
                )
            for candidate_id in candidate_ids:
                normalized_id = str(candidate_id or "").strip()
                if normalized_id and normalized_id not in lookup:
                    lookup[normalized_id] = matches[0]
    return lookup
