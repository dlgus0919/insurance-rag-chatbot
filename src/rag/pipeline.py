"""검색과 LLM 생성을 연결하는 RAG 파이프라인."""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.llm.prompt import SYSTEM_PROMPT, build_user_prompt
from src.parser.chunker import Chunk
from src.retrieval import Hit
from src.retrieval.hybrid import rrf_fuse


@dataclass
class RagAnswer:
    """RAG 답변 결과."""

    answer: str
    chunks: list[Chunk]
    timing: dict


def _hit_to_chunk(hit: Hit) -> Chunk:
    metadata = dict(hit.metadata)
    metadata.setdefault("char_count", len(hit.document))
    return Chunk(id=hit.id, text=hit.document, metadata=metadata)


class RagPipeline:
    """Dense 검색, BM25, RRF, Ollama 생성을 순서대로 실행한다."""

    def __init__(
        self,
        embedder,
        vector_store,
        bm25,
        llm,
        top_k_dense: int = 12,
        top_k_bm25: int = 12,
        top_k_final: int = 8,
        rrf_k: int = 60,
    ):
        self.embedder = embedder
        self.vector_store = vector_store
        self.bm25 = bm25
        self.llm = llm
        self.top_k_dense = top_k_dense
        self.top_k_bm25 = top_k_bm25
        self.top_k_final = top_k_final
        self.rrf_k = rrf_k

    def answer(self, question: str, temperature: float = 0.2) -> RagAnswer:
        """질문에 대해 답변과 사용한 청크를 반환한다."""

        total_started = time.perf_counter()
        retrieve_started = time.perf_counter()

        query_embedding = self.embedder.embed_query(question)
        dense_hits = self.vector_store.query(query_embedding, self.top_k_dense)
        bm25_hits = self.bm25.query(question, self.top_k_bm25)
        fused_hits = rrf_fuse(dense_hits, bm25_hits, top_k=self.top_k_final, rrf_k=self.rrf_k)
        chunks = [_hit_to_chunk(hit) for hit in fused_hits]

        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000
        prompt = build_user_prompt(question, chunks)

        llm_started = time.perf_counter()
        answer = self.llm.generate(prompt, system=SYSTEM_PROMPT, temperature=temperature)
        llm_ms = (time.perf_counter() - llm_started) * 1000
        total_ms = (time.perf_counter() - total_started) * 1000

        return RagAnswer(
            answer=answer,
            chunks=chunks,
            timing={
                "retrieve_ms": retrieve_ms,
                "llm_ms": llm_ms,
                "total_ms": total_ms,
            },
        )
