#!/usr/bin/env python3
"""PDF를 청크와 검색 인덱스로 변환하는 스크립트."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.parser.chunker import chunk_pages, load_chunks, save_chunks
from src.parser.pdf_parser import parse_pdf
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.vector_store import VectorStore


def build_chunks() -> None:
    """PDF에서 chunks.jsonl을 생성한다."""

    started = time.perf_counter()
    print("[M1] PDF 파싱 시작")
    pages = parse_pdf(config.PDF_PATH)
    non_empty_pages = sum(1 for _, text in pages if text.strip())
    print(f"[M1] PDF 파싱 완료: 전체 {len(pages)}페이지, 텍스트 {non_empty_pages}페이지")

    print("[M1] 청킹 시작")
    chunks = chunk_pages(
        pages,
        target_chars=config.CHUNK_TARGET_CHARS,
        overlap_chars=config.CHUNK_OVERLAP_CHARS,
    )
    save_chunks(chunks, config.CHUNKS_PATH)

    lengths = [chunk.metadata["char_count"] for chunk in chunks]
    code_chunks = sum(1 for chunk in chunks if chunk.metadata["codes"])
    avg_len = statistics.mean(lengths) if lengths else 0
    ratio = (code_chunks / len(chunks) * 100) if chunks else 0
    elapsed = time.perf_counter() - started

    print(f"[M1] 청킹 완료: {config.CHUNKS_PATH}")
    print(f"[M1] 청크 수: {len(chunks):,}")
    print(f"[M1] 평균 길이: {avg_len:.1f}자")
    print(f"[M1] 코드 포함 청크: {code_chunks:,}개 ({ratio:.1f}%)")
    print(f"[M1] 소요 시간: {elapsed:.1f}초")


def build_index() -> None:
    """chunks.jsonl에서 ChromaDB와 BM25 인덱스를 생성한다."""

    if not config.CHUNKS_PATH.exists():
        raise SystemExit(
            f"청크 파일이 없습니다: {config.CHUNKS_PATH}\n"
            "먼저 `python scripts/ingest.py --stage chunks`를 실행하세요."
        )

    started = time.perf_counter()
    print("[M2] 청크 로드 시작")
    chunks = load_chunks(config.CHUNKS_PATH)
    ids = [chunk.id for chunk in chunks]
    texts = [chunk.text for chunk in chunks]
    metadatas = [chunk.metadata for chunk in chunks]
    print(f"[M2] 청크 로드 완료: {len(chunks):,}개")

    print("[M2] BM25 인덱스 생성 시작")
    bm25_started = time.perf_counter()
    bm25 = BM25Index()
    bm25.build(ids, texts, metadatas)
    bm25.save(config.BM25_PATH)
    print(f"[M2] BM25 저장 완료: {config.BM25_PATH} ({time.perf_counter() - bm25_started:.1f}초)")

    print(f"[M2] 임베딩 모델 로드: {config.EMBEDDING_MODEL}")
    embedder = Embedder(config.EMBEDDING_MODEL)

    print("[M2] 문서 임베딩 시작")
    embed_started = time.perf_counter()
    embeddings = embedder.embed_documents(texts, batch_size=16)
    embed_elapsed = time.perf_counter() - embed_started
    print(f"[M2] 문서 임베딩 완료: {embeddings.shape} ({embed_elapsed:.1f}초)")

    print("[M2] ChromaDB 저장 시작")
    vector_store = VectorStore(config.CHROMA_DIR)
    vector_store.upsert(ids, embeddings, metadatas, texts)
    print(f"[M2] ChromaDB 저장 완료: {config.CHROMA_DIR}")

    print("[M2] 샘플 질의 retrieve: 재진 진찰료")
    query_embedding = embedder.embed_query("재진 진찰료")
    dense_hits = vector_store.query(query_embedding, top_k=5)
    bm25_hits = bm25.query("재진 진찰료", top_k=5)
    print("[M2] Dense 상위 5건")
    for hit in dense_hits:
        print(f"- {hit.id} score={hit.score:.4f} p.{hit.metadata.get('page_start')}")
    print("[M2] BM25 상위 5건")
    for hit in bm25_hits:
        print(f"- {hit.id} score={hit.score:.4f} p.{hit.metadata.get('page_start')}")
    print(f"[M2] 인덱싱 전체 소요 시간: {time.perf_counter() - started:.1f}초")


def main() -> None:
    parser = argparse.ArgumentParser(description="보험 고시 PDF 인제스트")
    parser.add_argument("--stage", choices=["chunks", "index", "all"], default="all")
    args = parser.parse_args()

    if args.stage in {"chunks", "all"}:
        build_chunks()
    if args.stage in {"index", "all"}:
        build_index()


if __name__ == "__main__":
    main()
