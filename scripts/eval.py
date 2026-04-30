#!/usr/bin/env python3
"""Smoke QA 평가 스크립트."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.llm.prompt import SYSTEM_PROMPT, build_user_prompt
from src.llm.ollama_client import OllamaClient
from src.parser.chunker import Chunk
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.hybrid import rrf_fuse
from src.retrieval.vector_store import VectorStore

SMOKE_QA_PATH = ROOT / "eval" / "smoke_qa.jsonl"


def load_questions(path: Path = SMOKE_QA_PATH) -> list[dict]:
    """JSONL 평가 문항을 읽는다."""

    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def hit_matches_expected_page(hit, expected_pages: list[int]) -> bool:
    """검색 결과 페이지 범위가 정답 페이지 중 하나를 포함하는지 확인한다."""

    start = hit.metadata.get("page_start")
    end = hit.metadata.get("page_end", start)
    if start is None:
        return False
    return any(start <= page <= end for page in expected_pages)


def answer_mentions_expected_page(answer: str, expected_pages: list[int]) -> bool:
    """답변 텍스트에 정답 페이지 번호가 언급됐는지 확인한다."""

    return any(f"p.{page}" in answer or f"p. {page}" in answer for page in expected_pages)


def _hit_to_chunk(hit) -> Chunk:
    metadata = dict(hit.metadata)
    metadata.setdefault("char_count", len(hit.document))
    return Chunk(id=hit.id, text=hit.document, metadata=metadata)


def main() -> None:
    questions = load_questions()
    if not questions:
        raise SystemExit("평가 문항이 없습니다.")
    if not config.BM25_PATH.exists():
        raise SystemExit("BM25 인덱스가 없습니다. `python scripts/ingest.py --stage index`를 먼저 실행하세요.")

    llm = OllamaClient(config.OLLAMA_HOST, config.OLLAMA_MODEL)
    if not llm.health():
        raise SystemExit("Ollama 서버에 연결할 수 없습니다. Ollama 데스크톱 앱 또는 `ollama serve`를 실행하세요.")

    embedder = Embedder(config.EMBEDDING_MODEL)
    vector_store = VectorStore(config.CHROMA_DIR)
    bm25 = BM25Index.load(config.BM25_PATH)

    recall_hits = 0
    page_hits = 0

    for index, item in enumerate(questions, start=1):
        question = item["question"]
        expected_pages = item["expected_pages"]
        query_embedding = embedder.embed_query(question)
        dense_hits = vector_store.query(query_embedding, config.TOP_K_DENSE)
        bm25_hits = bm25.query(question, config.TOP_K_BM25)
        fused_hits = rrf_fuse(dense_hits, bm25_hits, top_k=8, rrf_k=config.RRF_K)
        chunks = [_hit_to_chunk(hit) for hit in fused_hits]

        retrieved = any(hit_matches_expected_page(hit, expected_pages) for hit in fused_hits)
        recall_hits += int(retrieved)

        prompt = build_user_prompt(question, chunks)
        answer = llm.generate(prompt, system=SYSTEM_PROMPT, temperature=0.2)
        page_ok = answer_mentions_expected_page(answer, expected_pages)
        page_hits += int(page_ok)

        top_pages = [
            f"{hit.metadata.get('page_start')}-{hit.metadata.get('page_end')}"
            if hit.metadata.get("page_start") != hit.metadata.get("page_end")
            else str(hit.metadata.get("page_start"))
            for hit in fused_hits[:3]
        ]
        print(
            f"[{index:02d}] {item['type']} recall={'OK' if retrieved else 'MISS'} "
            f"page={'OK' if page_ok else 'MISS'} top_pages={top_pages}"
        )

    total = len(questions)
    recall = recall_hits / total
    page_accuracy = page_hits / total
    print(f"retrieval recall@8: {recall:.3f}")
    print(f"출처 페이지 정확도: {page_accuracy:.3f}")

    if recall < 0.7 or page_accuracy < 0.6:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
