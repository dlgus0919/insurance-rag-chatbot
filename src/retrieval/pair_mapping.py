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

_STABLE_PROVENANCE_FIELDS = (
    "doc_short",
    "doc_name",
    "pdf_filename",
    "page_start",
    "page_end",
    "chapter",
    "section",
    "part",
    "volume",
    "source_method",
)

_EQUIVALENCE_FIELDS = (
    "product_type",
    "is_own_company",
)


def _metadata_value(row: dict, field: str) -> str:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get(field) or "").strip()


def _normalized_text_hash(row: dict) -> str:
    text = re.sub(r"\s+", "", str(row.get("text") or ""))
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _source_provenance_key(row: dict) -> tuple[str, ...] | None:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return None
    text_hash = _normalized_text_hash(row)
    if not text_hash:
        return None
    return (text_hash, *(str(metadata.get(field) or "") for field in _SOURCE_PROVENANCE_FIELDS))


def _stable_provenance_key(row: dict) -> tuple[str, ...] | None:
    """Return a conservative document/page/segment identity for rechunked rows."""

    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return None
    has_document = bool(_metadata_value(row, "pdf_filename") or _metadata_value(row, "doc_name"))
    has_page = bool(_metadata_value(row, "page_start") or _metadata_value(row, "page_end"))
    has_segment = bool(
        _metadata_value(row, "chapter")
        or _metadata_value(row, "section")
        or _metadata_value(row, "part")
        or _metadata_value(row, "volume")
    )
    if not (has_document and has_page and has_segment):
        return None
    return tuple(_metadata_value(row, field) for field in _STABLE_PROVENANCE_FIELDS)


def _policy_generation_conflicts(indexed_row: dict, canonical_row: dict) -> bool:
    indexed_generation = _metadata_value(indexed_row, "policy_generation")
    canonical_generation = _metadata_value(canonical_row, "policy_generation")
    return bool(indexed_generation and canonical_generation and indexed_generation != canonical_generation)


def _canonical_equivalence_key(row: dict) -> tuple[str, ...] | None:
    stable_key = _stable_provenance_key(row)
    text_hash = _normalized_text_hash(row)
    if stable_key is None or not text_hash:
        return None
    return (
        *stable_key,
        text_hash,
        *(_metadata_value(row, field) for field in _EQUIVALENCE_FIELDS),
        _metadata_value(row, "policy_generation"),
    )


def _equivalent_canonical_match(matches: list[dict], indexed_row: dict) -> dict | None:
    if not matches or any(_policy_generation_conflicts(indexed_row, row) for row in matches):
        return None
    if len(matches) == 1:
        return matches[0]
    equivalence_classes: dict[tuple[str, ...], list[dict]] = {}
    for row in matches:
        key = _canonical_equivalence_key(row)
        if key is None:
            return None
        equivalence_classes.setdefault(key, []).append(row)
    if len(equivalence_classes) != 1:
        return None
    return min(next(iter(equivalence_classes.values())), key=lambda row: str(row.get("id") or ""))


def _explicit_reference_ids(row: dict) -> tuple[str, ...]:
    metadata = row.get("metadata")
    values = [row.get("id")]
    if isinstance(metadata, dict):
        values.extend(metadata.get(field) for field in ("source_chunk_id", "canonical_chunk_id", "variant_chunk_id"))
    return tuple(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))


def _explicit_canonical_match(indexed_row: dict, canonical_lookup: dict[str, dict]) -> tuple[bool, dict | None]:
    matches_by_id = {
        str(canonical_lookup[reference_id].get("id") or reference_id): canonical_lookup[reference_id]
        for reference_id in _explicit_reference_ids(indexed_row)
        if reference_id in canonical_lookup
    }
    matches = list(matches_by_id.values())
    if not matches:
        return False, None
    return True, _equivalent_canonical_match(matches, indexed_row)


def load_source_metadata_lookup(
    canonical_chunks_path: Path,
    indexed_chunks_path: Path | None = None,
) -> dict[str, dict]:
    """Load canonical metadata and conservative aliases for rechunked source IDs."""

    lookup = load_chunk_lookup(canonical_chunks_path)
    canonical_lookup = dict(lookup)
    if indexed_chunks_path is None or not indexed_chunks_path.exists():
        return lookup
    if indexed_chunks_path.resolve() == canonical_chunks_path.resolve():
        return lookup

    by_provenance: dict[tuple[str, ...], list[dict]] = {}
    by_stable_provenance: dict[tuple[str, ...], list[dict]] = {}
    for canonical_row in canonical_lookup.values():
        key = _source_provenance_key(canonical_row)
        if key is not None:
            by_provenance.setdefault(key, []).append(canonical_row)
        stable_key = _stable_provenance_key(canonical_row)
        if stable_key is not None:
            by_stable_provenance.setdefault(stable_key, []).append(canonical_row)

    with indexed_chunks_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            indexed_row = json.loads(line)
            has_explicit_match, match = _explicit_canonical_match(indexed_row, canonical_lookup)
            if not has_explicit_match:
                key = _source_provenance_key(indexed_row)
                exact_matches = by_provenance.get(key, []) if key is not None else []
                if exact_matches:
                    match = _equivalent_canonical_match(exact_matches, indexed_row)
                else:
                    stable_key = _stable_provenance_key(indexed_row)
                    stable_matches = by_stable_provenance.get(stable_key, []) if stable_key is not None else []
                    if stable_matches:
                        match = _equivalent_canonical_match(stable_matches, indexed_row)
            if match is None:
                continue
            source_metadata = indexed_row.get("metadata")
            candidate_ids = [indexed_row.get("id")]
            if isinstance(source_metadata, dict):
                candidate_ids.extend(
                    source_metadata.get(field)
                    for field in ("source_chunk_id", "canonical_chunk_id", "variant_chunk_id")
                )
            for candidate_id in candidate_ids:
                normalized_id = str(candidate_id or "").strip()
                if normalized_id and normalized_id not in lookup:
                    lookup[normalized_id] = match
    return lookup
