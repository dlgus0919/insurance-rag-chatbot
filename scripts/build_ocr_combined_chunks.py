#!/usr/bin/env python3
"""원본 OCR(v1) + 보정 OCR(v2) 청크를 통합해 단일 JSONL로 저장한다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parser.chunker import Chunk, load_chunks, save_chunks


def _with_version(chunks: list[Chunk], version: str) -> list[Chunk]:
    tagged: list[Chunk] = []
    for chunk in chunks:
        metadata = dict(chunk.metadata)
        metadata["ocr_version"] = version
        metadata["canonical_chunk_id"] = metadata.get("canonical_chunk_id") or metadata.get("source_chunk_id") or chunk.id
        metadata["source_chunk_id"] = metadata.get("source_chunk_id") or chunk.id
        tagged.append(Chunk(id=chunk.id, text=chunk.text, metadata=metadata))
    return tagged


def _reindex(chunks: list[Chunk]) -> list[Chunk]:
    merged: list[Chunk] = []
    for index, chunk in enumerate(chunks):
        doc_short = str(chunk.metadata.get("doc_short", "ocr"))
        version = str(chunk.metadata.get("ocr_version", "na"))
        safe_version = version.replace("/", "_").replace(" ", "_")
        chunk_id = f"{doc_short}_{safe_version}_ch_{index:06d}"
        merged.append(Chunk(id=chunk_id, text=chunk.text, metadata=dict(chunk.metadata)))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR v1+v2 통합 청크 생성")
    parser.add_argument(
        "--v1-chunks-path",
        type=Path,
        default=ROOT / "data" / "processed" / "chunks_v1_original_ocr.jsonl",
        help="원본 OCR 청크 JSONL 경로",
    )
    parser.add_argument(
        "--v2-chunks-path",
        type=Path,
        default=ROOT / "data" / "processed" / "chunks_v2_manual.jsonl",
        help="보정 OCR 청크 JSONL 경로",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=ROOT / "data" / "processed" / "chunks_v1_v2_combined.jsonl",
        help="통합 청크 출력 JSONL 경로",
    )
    args = parser.parse_args()

    v1_path = args.v1_chunks_path if args.v1_chunks_path.is_absolute() else ROOT / args.v1_chunks_path
    v2_path = args.v2_chunks_path if args.v2_chunks_path.is_absolute() else ROOT / args.v2_chunks_path
    out_path = args.output_path if args.output_path.is_absolute() else ROOT / args.output_path

    if not v1_path.exists():
        raise SystemExit(f"v1 청크 파일이 없습니다: {v1_path}")
    if not v2_path.exists():
        raise SystemExit(f"v2 청크 파일이 없습니다: {v2_path}")

    v1_chunks = _with_version(load_chunks(v1_path), "v1")
    v2_chunks = _with_version(load_chunks(v2_path), "v2_manual")
    combined = _reindex(v1_chunks + v2_chunks)
    save_chunks(combined, out_path)

    print(f"[combine] v1 chunks: {len(v1_chunks):,}")
    print(f"[combine] v2 chunks: {len(v2_chunks):,}")
    print(f"[combine] total chunks: {len(combined):,}")
    print(f"[combine] output: {out_path}")


if __name__ == "__main__":
    main()
