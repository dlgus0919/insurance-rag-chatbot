from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.parser.chunker import Chunk
from src.retrieval.chunk_lookup import build_chunk_lookup_metadata


def load_canonical_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def save_canonical_manifest(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def iter_chunks_for_index_mode(rows: list[dict[str, Any]], index_mode: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for row in rows:
        canonical_chunk_id = str(row.get("canonical_chunk_id") or "")
        doc_short = str(row.get("doc_short") or "")
        if not canonical_chunk_id or not doc_short:
            continue

        variants = row.get("source_variants", {}) or {}
        if index_mode == "v2_only":
            entry = variants.get("v2_only")
            if not isinstance(entry, dict) or not entry.get("available"):
                continue
            chunk = _chunk_from_variant(canonical_chunk_id, entry, row)
            if chunk is not None:
                chunks.append(chunk)
            continue

        if index_mode == "v1_v2_combined":
            entries = variants.get("v1_v2_combined") or []
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("available", True):
                    continue
                chunk = _chunk_from_variant(canonical_chunk_id, entry, row)
                if chunk is not None:
                    chunks.append(chunk)
            continue

        raise ValueError(f"Unsupported canonical manifest index mode: {index_mode}")
    return chunks


def _chunk_from_variant(canonical_chunk_id: str, entry: dict[str, Any], row: dict[str, Any]) -> Chunk | None:
    variant_chunk_id = str(entry.get("variant_chunk_id") or "")
    text = str(entry.get("text") or row.get("text") or "")
    if not variant_chunk_id or not text:
        return None

    metadata = dict(row.get("metadata") or {})
    metadata.update(dict(entry.get("metadata") or {}))
    metadata["doc_short"] = row.get("doc_short")
    metadata["doc_name"] = row.get("doc_name")
    metadata["pdf_filename"] = row.get("pdf_filename")
    metadata["page_start"] = row.get("page_start")
    metadata["page_end"] = row.get("page_end")
    metadata["canonical_chunk_id"] = canonical_chunk_id
    metadata["variant_chunk_id"] = variant_chunk_id
    metadata["source_chunk_id"] = metadata.get("source_chunk_id") or canonical_chunk_id
    metadata["ocr_version"] = entry.get("ocr_version")
    metadata = build_chunk_lookup_metadata(variant_chunk_id, metadata)
    metadata["canonical_chunk_id"] = canonical_chunk_id
    metadata["source_chunk_id"] = metadata.get("source_chunk_id") or canonical_chunk_id
    return Chunk(id=variant_chunk_id, text=text, metadata=metadata)
