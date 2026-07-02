#!/usr/bin/env python3
"""Build derived chunks/indexes from the canonical chunk manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ingest import build_index
from src.ingest.source_promotion import ACTIVE_SOURCE_CHUNKS_PATH, load_active_source_chunks
from src.parser.chunker import Chunk
from src.parser.chunker import save_chunks
from src.retrieval.canonical_manifest import iter_chunks_for_index_mode, load_canonical_manifest
from src.retrieval.index_mode import resolve_index_paths


def build_index_from_manifest(
    *,
    canonical_manifest: Path,
    index_mode: str,
    chunks_output: Path,
    index_root: Path,
    active_source_chunks: Path | None = ACTIVE_SOURCE_CHUNKS_PATH,
) -> dict[str, object]:
    rows = load_canonical_manifest(canonical_manifest)
    chunks = iter_chunks_for_index_mode(rows, index_mode)
    chunks = _merge_active_source_chunks(chunks, active_source_chunks)

    save_chunks(chunks, chunks_output)
    build_index(chunks_path=chunks_output, index_root=index_root)

    return {
        "index_mode": index_mode,
        "chunk_count": len(chunks),
        "chunks_output": chunks_output,
        "index_root": index_root,
        "active_source_chunks": active_source_chunks,
    }


def _merge_active_source_chunks(chunks: list[Chunk], active_source_chunks: Path | None) -> list[Chunk]:
    if not active_source_chunks:
        return list(chunks)
    if not active_source_chunks.exists():
        return list(chunks)
    return list(chunks) + load_active_source_chunks(active_source_chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build index from canonical chunk manifest")
    parser.add_argument("--canonical-manifest", type=Path, default=ROOT / "data" / "processed" / "chunks_canonical_manifest.jsonl")
    parser.add_argument("--active-source-chunks", type=Path, default=ACTIVE_SOURCE_CHUNKS_PATH, help="Optional active intake source chunks overlay")
    parser.add_argument("--index-mode", choices=["v2_only", "v1_v2_combined"], required=True)
    parser.add_argument("--chunks-output", type=Path, default=None, help="Optional derived chunks output path")
    parser.add_argument("--index-root", type=Path, default=None, help="Optional index root override")
    args = parser.parse_args()

    canonical_manifest = args.canonical_manifest if args.canonical_manifest.is_absolute() else ROOT / args.canonical_manifest
    active_source_chunks = args.active_source_chunks if args.active_source_chunks.is_absolute() else ROOT / args.active_source_chunks
    default_chunks_output, default_index_root = _defaults_for_mode(args.index_mode)
    chunks_output = args.chunks_output if args.chunks_output else default_chunks_output
    chunks_output = chunks_output if chunks_output.is_absolute() else ROOT / chunks_output
    index_root = args.index_root if args.index_root else default_index_root
    index_root = index_root if index_root.is_absolute() else ROOT / index_root

    result = build_index_from_manifest(
        canonical_manifest=canonical_manifest,
        index_mode=args.index_mode,
        chunks_output=chunks_output,
        index_root=index_root,
        active_source_chunks=active_source_chunks,
    )

    print(f"[canonical-index] mode: {args.index_mode}")
    print(f"[canonical-index] chunks: {result['chunk_count']:,}")
    print(f"[canonical-index] chunks_output: {chunks_output}")
    print(f"[canonical-index] index_root: {index_root}")
    print(f"[canonical-index] active_source_chunks: {active_source_chunks}")


def _defaults_for_mode(index_mode: str) -> tuple[Path, Path]:
    bm25_path, chroma_dir = resolve_index_paths(index_mode)
    return bm25_path.parent.parent / "processed" / (
        "chunks_v2_manual.jsonl" if index_mode == "v2_only" else "chunks_v1_v2_combined.jsonl"
    ), chroma_dir.parent


if __name__ == "__main__":
    main()
