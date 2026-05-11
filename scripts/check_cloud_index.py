#!/usr/bin/env python3
"""Print cloud index coverage by doc_short."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.retrieval.bm25 import BM25Index
from src.retrieval.vector_store import VectorStore


def _count_chunks() -> Counter[str]:
    counts: Counter[str] = Counter()
    if not config.CHUNKS_PATH.exists():
        return counts
    with config.CHUNKS_PATH.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            record = json.loads(line)
            metadata = record.get("metadata") or {}
            doc_short = str(metadata.get("doc_short") or "")
            if doc_short:
                counts[doc_short] += 1
    return counts


def _count_chroma() -> Counter[str]:
    counts: Counter[str] = Counter()
    if not (config.CHROMA_DIR.exists() and any(config.CHROMA_DIR.iterdir())):
        return counts
    try:
        store = VectorStore(config.CHROMA_DIR)
        entries = store.collection.get(include=["metadatas"])
    except Exception as exc:
        print(f"[check_cloud_index] ChromaDB 읽기 실패: {exc}", file=sys.stderr)
        return counts
    for metadata in entries.get("metadatas", []) or []:
        doc_short = str((metadata or {}).get("doc_short") or "")
        if doc_short:
            counts[doc_short] += 1
    return counts


def _count_bm25() -> Counter[str]:
    counts: Counter[str] = Counter()
    if not config.BM25_PATH.exists():
        return counts
    try:
        bm25 = BM25Index.load(config.BM25_PATH)
    except Exception as exc:
        print(f"[check_cloud_index] BM25 읽기 실패: {exc}", file=sys.stderr)
        return counts
    for metadata in bm25.metadatas:
        doc_short = str((metadata or {}).get("doc_short") or "")
        if doc_short:
            counts[doc_short] += 1
    return counts


def _print_counts(title: str, counts: Counter[str], doc_order: list[str]) -> None:
    print(f"\n[{title}]")
    seen: set[str] = set()
    for doc_short in doc_order:
        print(f"{doc_short}: {counts.get(doc_short, 0)}")
        seen.add(doc_short)
    for doc_short in sorted(set(counts) - seen):
        print(f"{doc_short}: {counts[doc_short]}")


def main() -> int:
    target_docs = list(config.INDEXED_DOC_SHORT_ORDER)
    all_docs = list(dict.fromkeys(config.DOC_SHORT_ORDER + target_docs))
    chunk_counts = _count_chunks()
    chroma_counts = _count_chroma()
    bm25_counts = _count_bm25()

    _print_counts("chunks.jsonl", chunk_counts, all_docs)
    _print_counts("ChromaDB", chroma_counts, all_docs)
    _print_counts("BM25", bm25_counts, all_docs)

    missing = [
        doc_short
        for doc_short in target_docs
        if chunk_counts.get(doc_short, 0) > 0 and chroma_counts.get(doc_short, 0) == 0
    ]
    print("\n[missing cloud vectors]")
    if missing:
        for doc_short in missing:
            print(f"- {doc_short}")
    else:
        print("None")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
