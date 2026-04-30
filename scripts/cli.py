#!/usr/bin/env python3
"""콘솔 RAG 검증용 챗 루프."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.llm.ollama_client import OllamaClient
from src.rag.pipeline import RagPipeline
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.vector_store import VectorStore


def _source_label(chunk) -> str:
    metadata = chunk.metadata
    start = metadata.get("page_start")
    end = metadata.get("page_end")
    page = f"p.{start}" if start == end or end is None else f"p.{start}-{end}"
    hierarchy = " / ".join(
        str(value)
        for value in [
            metadata.get("volume"),
            metadata.get("part"),
            metadata.get("chapter"),
            metadata.get("section"),
        ]
        if value
    )
    return f"{chunk.id} | {hierarchy} | {page}"


def load_pipeline() -> RagPipeline:
    """기본 설정으로 파이프라인을 로드한다."""

    if not config.BM25_PATH.exists():
        raise RuntimeError("BM25 인덱스가 없습니다. `python scripts/ingest.py --stage index`를 먼저 실행하세요.")
    llm = OllamaClient(config.OLLAMA_HOST, config.OLLAMA_MODEL)
    if not llm.health():
        raise RuntimeError("Ollama 서버에 연결할 수 없습니다. Ollama 데스크톱 앱 또는 `ollama serve`를 실행하세요.")
    embedder = Embedder(config.EMBEDDING_MODEL)
    vector_store = VectorStore(config.CHROMA_DIR)
    bm25 = BM25Index.load(config.BM25_PATH)
    return RagPipeline(
        embedder=embedder,
        vector_store=vector_store,
        bm25=bm25,
        llm=llm,
        top_k_dense=config.TOP_K_DENSE,
        top_k_bm25=config.TOP_K_BM25,
        top_k_final=config.TOP_K_FINAL,
        rrf_k=config.RRF_K,
    )


def main() -> None:
    try:
        pipeline = load_pipeline()
    except RuntimeError as exc:
        print(f"[오류] {exc}")
        raise SystemExit(1) from exc

    print("보험 고시 문서 RAG 챗봇 CLI입니다. 종료하려면 :q 를 입력하세요.")
    while True:
        question = input("\n질문> ").strip()
        if question == ":q":
            break
        if not question:
            continue
        try:
            result = pipeline.answer(question)
        except RuntimeError as exc:
            print(f"[오류] {exc}")
            continue

        print("\n답변")
        print(result.answer)
        print("\n출처")
        for chunk in result.chunks:
            print(f"- {_source_label(chunk)}")


if __name__ == "__main__":
    main()
