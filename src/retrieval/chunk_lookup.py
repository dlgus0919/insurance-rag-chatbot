from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class ChunkLookupRef:
    requested_id: str
    canonical_chunk_id: str | None = None
    source_chunk_id: str | None = None
    doc_short: str | None = None
    page_start: int | None = None
    page_end: int | None = None


def canonical_source_chunk_id(chunk_id: str) -> str:
    """Collapse index-mode-specific chunk ids onto a stable source chunk id."""

    return re.sub(r"_(?:v1|v2|v1_original|v2_manual|v1_v2_combined)(?=_ch_)", "", chunk_id)


def graph_chunk_fallback_ids(chunk_id: str) -> list[str]:
    """Build conservative string fallbacks for legacy chunk ids."""

    fallbacks: list[str] = []
    normalized_id = re.sub(r"_(?:v2_manual|v1_original|v1_v2_combined)(?=_ch_)", "", chunk_id)
    if normalized_id != chunk_id:
        fallbacks.append(normalized_id)
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
    for marker in ("_v2_manual_", "_v1_original_", "_v1_v2_combined_"):
        if marker in chunk_id:
            fallbacks.append(chunk_id.replace(marker, "_"))

    unique: list[str] = []
    seen: set[str] = set()
    for fallback in fallbacks:
        if fallback != chunk_id and fallback not in seen:
            seen.add(fallback)
            unique.append(fallback)
    return unique


def build_chunk_lookup_metadata(chunk_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Ensure every chunk stores a stable cross-index lookup key."""

    enriched = dict(metadata)
    canonical_chunk_id = str(enriched.get("canonical_chunk_id") or canonical_source_chunk_id(chunk_id))
    source_chunk_id = str(enriched.get("source_chunk_id") or canonical_chunk_id)
    enriched["canonical_chunk_id"] = canonical_chunk_id
    enriched["source_chunk_id"] = source_chunk_id
    return enriched
