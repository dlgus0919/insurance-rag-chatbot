#!/usr/bin/env python3
"""Smoke QA 평가 스크립트."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.llm.ollama_client import OllamaClient
from src.parser.chunker import Chunk
from src.rag.pipeline import RagPipeline
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
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
    """
    답변 텍스트에 정답 페이지 번호가 언급됐는지 확인한다.

    단일 페이지 형식(p.38)과 범위 형식(p.36-38)을 모두 인정한다.
    범위 형식은 expected_pages 중 하나가 범위 안에 있으면 정답이다.
    """

    for page in expected_pages:
        single_page_pattern = rf"p\.\s*{page}(?!\d)"
        if re.search(single_page_pattern, answer):
            return True

    for match in re.finditer(r"p\.\s*(\d+)\s*-\s*(\d+)", answer):
        range_start, range_end = int(match.group(1)), int(match.group(2))
        if range_start > range_end:
            range_start, range_end = range_end, range_start
        if any(range_start <= page <= range_end for page in expected_pages):
            return True

    return False


def answer_mentions_expected_codes(answer: str, expected_codes: list[str]) -> bool:
    """답변 텍스트에 기대 코드가 모두 포함됐는지 확인한다."""

    if not expected_codes:
        return True
    normalized = answer.upper()
    return all(code.upper() in normalized for code in expected_codes)


def filter_chunks_by_doc(chunks, doc_sources: list[str] | None):
    """doc_sources가 있으면 해당 문서 출처의 청크/검색 결과만 남긴다."""

    if not doc_sources:
        return chunks
    allowed = set(doc_sources)
    return [chunk for chunk in chunks if chunk.metadata.get("doc_short") in allowed]


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
    pipeline = RagPipeline(
        embedder=embedder,
        vector_store=vector_store,
        bm25=bm25,
        llm=llm,
        top_k_dense=config.TOP_K_DENSE,
        top_k_bm25=config.TOP_K_BM25,
        top_k_final=config.TOP_K_FINAL,
        rrf_k=config.RRF_K,
    )
    indexed_doc_sources = {metadata.get("doc_short") for metadata in bm25.metadatas if metadata.get("doc_short")}

    recall_hits = 0
    page_hits = 0
    evaluated = 0
    skipped = 0

    for index, item in enumerate(questions, start=1):
        question = item["question"]
        expected_pages = item["expected_pages"]
        doc_sources = item.get("doc_sources")
        missing_sources = set(doc_sources or []) - indexed_doc_sources
        if item.get("type") == "cross_doc" and missing_sources:
            skipped += 1
            missing_label = ", ".join(sorted(missing_sources))
            print(f"[{index:02d}] {item['type']} skipped({missing_label} 미인덱싱)")
            continue

        fused_hits = pipeline.retrieve_hits(question, top_k=8)
        fused_hits = filter_chunks_by_doc(fused_hits, doc_sources)
        chunks = [_hit_to_chunk(hit) for hit in fused_hits]

        retrieved = any(hit_matches_expected_page(hit, expected_pages) for hit in fused_hits)
        recall_hits += int(retrieved)

        prompt = build_user_prompt(question, chunks)
        answer = llm.generate(prompt, system=SYSTEM_PROMPT, temperature=0.2)
        answer = append_retrieved_source_citations(answer, chunks)
        page_ok = answer_mentions_expected_page(answer, expected_pages)
        code_ok = answer_mentions_expected_codes(answer, item.get("expected_codes", []))
        page_hits += int(page_ok)

        top_pages = [
            f"{hit.metadata.get('page_start')}-{hit.metadata.get('page_end')}"
            if hit.metadata.get("page_start") != hit.metadata.get("page_end")
            else str(hit.metadata.get("page_start"))
            for hit in fused_hits[:3]
        ]
        print(
            f"[{index:02d}] {item['type']} recall={'OK' if retrieved else 'MISS'} "
            f"page={'OK' if page_ok else 'MISS'} "
            f"code={'OK' if code_ok else 'MISS'} top_pages={top_pages}"
        )
        evaluated += 1

    if evaluated == 0:
        raise SystemExit("평가 가능한 문항이 없습니다.")
    recall = recall_hits / evaluated
    page_accuracy = page_hits / evaluated
    print(f"retrieval recall@8: {recall:.3f}")
    print(f"출처 페이지 정확도: {page_accuracy:.3f}")
    if skipped:
        print(f"skipped: {skipped}")

    if recall < 0.7 or page_accuracy < 0.6:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
