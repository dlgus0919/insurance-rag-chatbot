"""검색과 LLM 생성을 연결하는 RAG 파이프라인."""

from __future__ import annotations

import time
import re
from dataclasses import dataclass

from src import config
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.parser.chunker import Chunk
from src.retrieval import Hit
from src.retrieval.hybrid import rrf_fuse
from src.retrieval.reranker import build_reranker


_CODE_PATTERN = re.compile(r"(?<![A-Z0-9.])(?:[A-Z]\d{2}(?:\.\d{1,2})?|[A-Z]{1,3}\d{2,5})(?![A-Z0-9.])")


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


def _extract_query_codes(question: str) -> list[str]:
    """질문에서 의료 코드 패턴을 추출하고 순서를 보존해 중복 제거한다."""

    codes: list[str] = []
    seen: set[str] = set()
    for match in _CODE_PATTERN.findall(question.upper()):
        if match not in seen:
            seen.add(match)
            codes.append(match)
    return codes


def _expand_retrieval_query(question: str) -> str:
    """검색 안정성을 위해 명세 범위의 동의어를 보강한다."""

    normalized = question.replace(" ", "")
    asks_items = any(keyword in question for keyword in ["항목", "무엇", "해당"])
    if "3대비급여" in normalized and asks_items:
        terms = "도수치료 체외충격파치료 증식치료 주사료 자기공명영상진단 MRI MRA 용어 정의"
        return f"{question} {terms}"
    return question


def _is_low_value_wide_range(hit: Hit) -> bool:
    """목차처럼 넓은 페이지 범위에 짧게 걸친 청크를 검색 후보에서 제외한다."""

    start = hit.metadata.get("page_start")
    end = hit.metadata.get("page_end", start)
    if start is None or end is None:
        return False
    char_count = hit.metadata.get("char_count", len(hit.document))
    return (end - start) > 10 and char_count < 300


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
        reranker=None,
        reranker_enabled: bool | None = None,
    ):
        self.embedder = embedder
        self.vector_store = vector_store
        self.bm25 = bm25
        self.llm = llm
        self.top_k_dense = top_k_dense
        self.top_k_bm25 = top_k_bm25
        self.top_k_final = top_k_final
        self.rrf_k = rrf_k
        if reranker is not None:
            self.reranker = reranker
        else:
            enabled = config.RERANKER_ENABLED if reranker_enabled is None else reranker_enabled
            self.reranker = build_reranker(enabled=enabled)

    def retrieve_hits(self, question: str, top_k: int | None = None) -> list[Hit]:
        """질문에 대한 최종 검색 후보를 반환한다."""

        final_top_k = top_k or self.top_k_final
        retrieval_query = _expand_retrieval_query(question)
        query_embedding = self.embedder.embed_query(retrieval_query)
        query_codes = _extract_query_codes(question)
        code_hits: list[Hit] = []

        if query_codes and hasattr(self.vector_store, "query_with_filter"):
            half_k = max(1, self.top_k_dense // 2)
            code_hits = self.vector_store.query_with_filter(
                query_embedding,
                filter_codes=query_codes,
                top_k=half_k,
                prefer_non_table=True,
            )
            general_top_k = half_k if code_hits else self.top_k_dense
            general_hits = self.vector_store.query(query_embedding, general_top_k)
            seen = {hit.id for hit in code_hits}
            dense_hits = code_hits + [hit for hit in general_hits if hit.id not in seen]
        else:
            dense_hits = self.vector_store.query(query_embedding, self.top_k_dense)

        bm25_hits = self.bm25.query(retrieval_query, self.top_k_bm25)
        dense_hits = [hit for hit in dense_hits if not _is_low_value_wide_range(hit)]
        bm25_hits = [hit for hit in bm25_hits if not _is_low_value_wide_range(hit)]
        reranker_enabled = self.reranker is not None and getattr(self.reranker, "enabled", True)
        rrf_top_k = final_top_k * 2 if reranker_enabled else final_top_k
        fused_hits = rrf_fuse(dense_hits, bm25_hits, top_k=rrf_top_k, rrf_k=self.rrf_k)
        if code_hits:
            fused_by_id = {hit.id: hit for hit in fused_hits}
            ordered: list[Hit] = []
            seen: set[str] = set()
            for hit in code_hits:
                ordered.append(fused_by_id.get(hit.id, hit))
                seen.add(hit.id)
            ordered.extend(hit for hit in fused_hits if hit.id not in seen)
            fused_hits = ordered[:rrf_top_k]
        if self.reranker is not None:
            return self.reranker.rerank(question, fused_hits, top_k=final_top_k)
        return fused_hits[:final_top_k]

    def answer(self, question: str, temperature: float = 0.2, top_k: int | None = None) -> RagAnswer:
        """질문에 대해 답변과 사용한 청크를 반환한다."""

        total_started = time.perf_counter()
        retrieve_started = time.perf_counter()

        fused_hits = self.retrieve_hits(question, top_k=top_k)
        chunks = [_hit_to_chunk(hit) for hit in fused_hits]

        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000
        prompt = build_user_prompt(question, chunks)

        llm_started = time.perf_counter()
        answer = self.llm.generate(prompt, system=SYSTEM_PROMPT, temperature=temperature)
        answer = append_retrieved_source_citations(answer, chunks)
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
