#!/usr/bin/env python3
"""Rebuild cloud-safe ChromaDB and BM25 indexes from committed chunks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.vector_store import VectorStore


def _cloud_doc_shorts() -> set[str]:
    return {source.doc_short for source in config.INDEXED_PDF_SOURCES}


def _load_cloud_chunks() -> tuple[list[str], list[str], list[dict]]:
    allowed_docs = _cloud_doc_shorts()
    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []

    if not config.CHUNKS_PATH.exists():
        raise RuntimeError(f"chunks.jsonl을 찾을 수 없습니다: {config.CHUNKS_PATH}")

    with config.CHUNKS_PATH.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            record = json.loads(line)
            metadata = dict(record.get("metadata") or {})
            if metadata.get("doc_short") not in allowed_docs:
                continue
            ids.append(str(record["id"]))
            texts.append(str(record.get("text", "")))
            metadatas.append(metadata)

    if not ids:
        raise RuntimeError("cloud_safe=True, requires_ocr=False 조건에 맞는 청크가 없습니다.")
    return ids, texts, metadatas


def _zip_chroma_dir(zip_output: Path) -> None:
    if not config.CHROMA_DIR.exists():
        raise RuntimeError(f"ChromaDB 디렉터리를 찾을 수 없습니다: {config.CHROMA_DIR}")

    zip_output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(config.CHROMA_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(config.ROOT_DIR))


def rebuild_from_chunks(zip_output: Path | None = None) -> dict:
    """Rebuild cloud-only ChromaDB and BM25 indexes from data/processed/chunks.jsonl."""

    load_dotenv(ROOT / ".env")
    ids, texts, metadatas = _load_cloud_chunks()
    embedder = Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
    embeddings = embedder.embed_documents(texts)

    vector_store = VectorStore(config.CHROMA_DIR, reset=True)
    vector_store.upsert(ids, embeddings, metadatas, texts)

    bm25 = BM25Index()
    bm25.build(ids, texts, metadatas)
    bm25.save(config.BM25_PATH)

    if zip_output is not None:
        _zip_chroma_dir(zip_output)

    return {
        "chunks": len(ids),
        "docs": sorted({str(metadata.get("doc_short")) for metadata in metadatas}),
        "zip_output": str(zip_output) if zip_output is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Rebuild cloud-safe ChromaDB and BM25 indexes from chunks.jsonl")
    parser.add_argument("--zip-output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        result = rebuild_from_chunks(zip_output=args.zip_output)
    except Exception as exc:
        print(f"[build_cloud_index] 재빌드 실패: {exc}", file=sys.stderr)
        return 1

    print("[build_cloud_index] 재빌드 완료")
    print(f"chunks: {result['chunks']}")
    print("docs: " + ", ".join(result["docs"]))
    if result["zip_output"]:
        print(f"zip: {result['zip_output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
