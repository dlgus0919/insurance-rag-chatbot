#!/usr/bin/env python3
"""Build a canonical chunk manifest shared by v2_only, v1_v2_combined, and GraphDB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parser.chunker import load_chunks
from src.retrieval.chunk_lookup import build_chunk_lookup_metadata, canonical_source_chunk_id
from src.retrieval.canonical_manifest import save_canonical_manifest


def _load_mapping_dir(mapping_dir: Path) -> tuple[dict[str, str], set[str]]:
    v1_to_canonical: dict[str, str] = {}
    mapped_v1_ids: set[str] = set()
    if not mapping_dir.exists():
        return v1_to_canonical, mapped_v1_ids
    for path in sorted(mapping_dir.glob("v1_v2_pairs_*.jsonl")):
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                row = json.loads(line)
                canonical_id = str(row.get("canonical_chunk_id") or "").strip()
                v1_id = str(row.get("v1_chunk_id") or "").strip()
                if not canonical_id or not v1_id:
                    continue
                v1_to_canonical[v1_id] = canonical_id
                mapped_v1_ids.add(v1_id)
    return v1_to_canonical, mapped_v1_ids


def _chunk_to_variant(chunk, *, variant_chunk_id: str | None = None, ocr_version: str | None = None) -> dict[str, Any]:
    metadata = build_chunk_lookup_metadata(chunk.id, chunk.metadata)
    return {
        "variant_chunk_id": variant_chunk_id or chunk.id,
        "ocr_version": ocr_version or metadata.get("ocr_version"),
        "available": True,
        "text": chunk.text,
        "metadata": metadata,
    }


def _looks_like_v2_manual(metadata: dict[str, Any]) -> bool:
    ocr_version = str(metadata.get("ocr_version") or metadata.get("source_version") or metadata.get("version") or "")
    if "v2" in ocr_version:
        return True
    source_method = str(metadata.get("source_method") or "")
    return "manual" in source_method.lower()


def _ensure_row(rows: dict[str, dict[str, Any]], canonical_id: str, chunk) -> dict[str, Any]:
    metadata = build_chunk_lookup_metadata(chunk.id, chunk.metadata)
    row = rows.get(canonical_id)
    if row is not None:
        return row
    row = {
        "canonical_chunk_id": canonical_id,
        "doc_short": metadata.get("doc_short"),
        "doc_name": metadata.get("doc_name"),
        "pdf_filename": metadata.get("pdf_filename"),
        "page_start": metadata.get("page_start"),
        "page_end": metadata.get("page_end"),
        "section_path": [
            value
            for value in (
                metadata.get("volume"),
                metadata.get("part"),
                metadata.get("chapter"),
                metadata.get("section"),
            )
            if value
        ],
        "content_type": metadata.get("content_type", "text"),
        "text": chunk.text,
        "token_count": len(chunk.text.split()),
        "metadata": metadata,
        "source_variants": {},
    }
    rows[canonical_id] = row
    return row


def build_manifest(
    *,
    v2_chunks_path: Path,
    v1_chunks_path: Path | None,
    combined_chunks_path: Path | None,
    mapping_dir: Path | None,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    v2_chunks = load_chunks(v2_chunks_path)
    for chunk in v2_chunks:
        metadata = build_chunk_lookup_metadata(chunk.id, chunk.metadata)
        canonical_id = str(metadata.get("canonical_chunk_id") or canonical_source_chunk_id(chunk.id))
        row = _ensure_row(rows, canonical_id, chunk)
        row["text"] = chunk.text
        row["metadata"] = metadata
        row["source_variants"]["v2_only"] = _chunk_to_variant(chunk, ocr_version="v2_manual")

    combined_by_canonical: dict[str, list[dict[str, Any]]] = {}
    if combined_chunks_path and combined_chunks_path.exists():
        for chunk in load_chunks(combined_chunks_path):
            metadata = build_chunk_lookup_metadata(chunk.id, chunk.metadata)
            canonical_id = str(metadata.get("canonical_chunk_id") or metadata.get("source_chunk_id") or canonical_source_chunk_id(chunk.id))
            row = _ensure_row(rows, canonical_id, chunk)
            if _looks_like_v2_manual(metadata) and "v2_only" not in row["source_variants"]:
                row["source_variants"]["v2_only"] = _chunk_to_variant(
                    chunk,
                    variant_chunk_id=str(metadata.get("source_chunk_id") or canonical_id),
                    ocr_version="v2_manual",
                )
            combined_by_canonical.setdefault(canonical_id, []).append(
                _chunk_to_variant(
                    chunk,
                    variant_chunk_id=chunk.id,
                    ocr_version=str(metadata.get("ocr_version") or ""),
                )
            )
        for canonical_id, entries in combined_by_canonical.items():
            rows[canonical_id]["source_variants"]["v1_v2_combined"] = entries

    v1_to_canonical, mapped_v1_ids = _load_mapping_dir(mapping_dir) if mapping_dir else ({}, set())
    if v1_chunks_path and v1_chunks_path.exists():
        for chunk in load_chunks(v1_chunks_path):
            metadata = build_chunk_lookup_metadata(chunk.id, chunk.metadata)
            canonical_id = v1_to_canonical.get(chunk.id) or str(metadata.get("canonical_chunk_id") or canonical_source_chunk_id(chunk.id))
            row = _ensure_row(rows, canonical_id, chunk)
            row["source_variants"]["v1"] = _chunk_to_variant(chunk, ocr_version="v1_original")
        # no-op variable read for clarity: unmatched v1 chunks intentionally become standalone canonical rows
        _ = mapped_v1_ids

    return sorted(rows.values(), key=lambda row: (str(row.get("doc_short") or ""), int(row.get("page_start") or 0), str(row.get("canonical_chunk_id") or "")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical chunk manifest")
    parser.add_argument("--v2-chunks-path", type=Path, default=ROOT / "data" / "processed" / "chunks_v2_manual.jsonl")
    parser.add_argument("--v1-chunks-path", type=Path, default=ROOT / "data" / "processed" / "chunks_v1_original_ocr.jsonl")
    parser.add_argument("--combined-chunks-path", type=Path, default=ROOT / "data" / "processed" / "chunks_v1_v2_combined.jsonl")
    parser.add_argument("--mapping-dir", type=Path, default=ROOT / "data" / "mapping")
    parser.add_argument("--output-path", type=Path, default=ROOT / "data" / "processed" / "chunks_canonical_manifest.jsonl")
    args = parser.parse_args()

    manifest = build_manifest(
        v2_chunks_path=args.v2_chunks_path if args.v2_chunks_path.is_absolute() else ROOT / args.v2_chunks_path,
        v1_chunks_path=args.v1_chunks_path if args.v1_chunks_path.is_absolute() else ROOT / args.v1_chunks_path,
        combined_chunks_path=args.combined_chunks_path if args.combined_chunks_path.is_absolute() else ROOT / args.combined_chunks_path,
        mapping_dir=args.mapping_dir if args.mapping_dir.is_absolute() else ROOT / args.mapping_dir,
    )
    output_path = args.output_path if args.output_path.is_absolute() else ROOT / args.output_path
    save_canonical_manifest(manifest, output_path)
    print(f"[canonical-manifest] rows: {len(manifest):,}")
    print(f"[canonical-manifest] output: {output_path}")


if __name__ == "__main__":
    main()
