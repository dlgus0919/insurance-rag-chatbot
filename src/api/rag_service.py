"""RAG pipeline loading and prompt helpers for the API layer."""

from __future__ import annotations

from functools import lru_cache
import logging
import re
from typing import Any

from src import config
from src.api.models import ChatMessage
from src.graph.context import build_graph_context
from src.llm.factory import build_llm
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.rag.evidence import append_evidence_validation_warning
from src.rag.pipeline import RagPipeline, _deterministic_guard_answer, _hit_to_chunk
from src.rag.table_store import TableStore
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.index_mode import INDEX_MODES, resolve_index_paths
from src.retrieval.reranker import build_reranker
from src.retrieval.vector_store import VectorStore


logger = logging.getLogger(__name__)


QUICKCODE_SYSTEM_PROMPT = (
    "당신은 신한EZ손해보험 보상 심사를 돕는 정형 코드 검색 어시스턴트입니다. "
    "아래 제공되는 정형 매핑 데이터는 신한EZ손해보험의 절대적인 보상 심사 기준이므로, "
    "이 수치와 조건을 왜곡하지 말고 기반하여 답변하시오."
)

_TABLE_STORE = TableStore()
_CODE_OR_RATE_PATTERN = re.compile(r"[A-Z]{1,3}\d{2,5}(?:\.\d{1,2})?|\d+\s*%|장해율\s*\d+", re.IGNORECASE)
_PRODUCT_DOC_FILTERS = {
    "medical": ["약관"],
    "actual_loss": ["약관"],
    "driver": ["자사_SOL운전자"],
    "health": ["자사_SOL건강"],
    "standard": ["표준약관"],
}


@lru_cache(maxsize=4)
def _load_heavy_components(index_mode: str):
    bm25_path, chroma_dir = _resolve_index_paths(index_mode)
    if not bm25_path.exists():
        raise RuntimeError(
            f"BM25 인덱스가 없습니다: {bm25_path}. "
            "`python scripts/ingest.py --stage index`를 먼저 실행하세요."
        )
    embedder = Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
    vector_store = VectorStore(chroma_dir)
    bm25 = BM25Index.load(bm25_path)
    reranker = build_reranker(enabled=config.RERANKER_ENABLED)
    return embedder, vector_store, bm25, reranker


@lru_cache(maxsize=16)
def get_rag_pipeline(
    model: str,
    top_k: int,
    index_mode: str = "default",
) -> RagPipeline:
    """Build a cached RAG pipeline for API requests."""

    embedder, vector_store, bm25, reranker = _load_heavy_components(index_mode)
    llm = build_llm(model)
    return RagPipeline(
        embedder=embedder,
        vector_store=vector_store,
        bm25=bm25,
        llm=llm,
        top_k_dense=config.TOP_K_DENSE,
        top_k_bm25=config.TOP_K_BM25,
        top_k_final=top_k,
        rrf_k=config.RRF_K,
        reranker=reranker,
    )


def _resolve_index_paths(index_mode: str):
    normalized = (index_mode or "default").strip().lower()
    if normalized in INDEX_MODES:
        return resolve_index_paths(normalized)
    version = config.normalize_ocr_version(normalized)
    paths = config.get_ingest_paths(version)
    return paths["bm25_path"], paths["chroma_dir"]


def chunk_to_source(chunk) -> dict:
    """Convert a retrieved chunk into frontend source metadata."""

    metadata = chunk.metadata
    page_start = metadata.get("page_start")
    page_end = metadata.get("page_end", page_start)
    return {
        "filename": metadata.get("pdf_filename") or metadata.get("source") or metadata.get("doc_short") or "문서",
        "doc_short": metadata.get("doc_short"),
        "page": page_start,
        "page_end": page_end,
        "chunk_id": chunk.id,
        "snippet": chunk.text[:180],
    }


def summarize_legacy_messages(messages: list[ChatMessage]) -> str:
    """Compress older history into a compact text summary for prompt context."""

    if not messages:
        return ""
    lines = []
    for message in messages:
        content = " ".join(message.content.split())
        lines.append(f"{message.role}: {content[:220]}")
    return "[이전 대화 요약본]\n" + "\n".join(lines)


def build_contextual_prompt(question: str, chunks: list, history: list[ChatMessage]) -> str:
    """Build a RAG prompt with compressed history and latest two turns."""

    older = history[:-4]
    latest = history[-4:]
    parts = []
    summary = summarize_legacy_messages(older)
    if summary:
        parts.append(summary)
    if latest:
        recent_lines = ["[최근 대화 원문]"]
        for message in latest:
            recent_lines.append(f"{message.role}: {message.content}")
        parts.append("\n".join(recent_lines))
    parts.append(build_user_prompt(question, chunks))
    return "\n\n".join(parts)


async def prepare_retrieved_context(
    pipeline: RagPipeline,
    question: str,
    top_k: int,
    history: list[ChatMessage],
):
    """Retrieve chunks, GraphDB facts, source metadata, and a prompt for generation."""

    graph_result = None
    graph_context = ""
    graph_hits = []
    warnings: list[dict[str, str]] = []

    if getattr(pipeline, "graph_enabled", False) and getattr(pipeline, "graph_retriever", None):
        try:
            graph_result = pipeline.graph_retriever.retrieve(question)
            graph_context = build_graph_context(graph_result)
            source_chunk_ids = getattr(graph_result, "source_chunk_ids", []) or []
            if source_chunk_ids:
                graph_hits = pipeline.vector_store.get_by_ids(source_chunk_ids)
                found_ids = {hit.id for hit in graph_hits}
                missing_ids = [chunk_id for chunk_id in source_chunk_ids if chunk_id not in found_ids]
                if missing_ids:
                    warnings.append({
                        "code": "GRAPH_SOURCE_CHUNKS_MISSING",
                        "message": f"GraphDB 근거 chunk 일부를 VectorStore에서 찾지 못했습니다: {', '.join(missing_ids[:5])}",
                    })
        except Exception as exc:  # pragma: no cover - runtime fallback
            logger.warning("Graph retrieval failed in API path: %s", exc, exc_info=True)
            warnings.append({
                "code": "GRAPH_RETRIEVAL_FAILED",
                "message": "GraphDB 근거 조회 중 오류가 발생해 일반 RAG로 답변합니다.",
            })
            graph_result = None
            graph_context = ""
            graph_hits = []

    hits, _ = pipeline.retrieve_hits(question, top_k=top_k, graph_hits=graph_hits)
    chunks = [_hit_to_chunk(hit) for hit in hits]
    sources = [chunk_to_source(chunk) for chunk in chunks]
    prompt = pipeline.build_prompt(question, chunks, graph_context=graph_context)
    history_context = build_history_context(history)
    if history_context:
        prompt = f"{history_context}\n\n{prompt}"
    deterministic_answer = _deterministic_guard_answer(question, chunks)
    return chunks, sources, prompt, graph_result_to_payload(graph_result), warnings, deterministic_answer


def extract_structured_terms(query: str) -> list[str]:
    """Extract likely code/rate terms while preserving the raw query as a fallback."""

    terms = [match.group(0).strip() for match in _CODE_OR_RATE_PATTERN.finditer(query)]
    if query.strip() not in terms:
        terms.append(query.strip())
    return [term for term in terms if term]


def _format_table_row(row: dict, row_type: str) -> str:
    lines = [f"[정형 매핑 데이터: {row_type}]"]
    for key, value in row.items():
        if value is None or str(value) == "":
            continue
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def build_history_context(messages: list[ChatMessage]) -> str:
    """Build compact chat history without replacing the current RAG prompt."""

    if not messages:
        return ""
    recent = messages[-4:]
    lines = ["[최근 대화 참고]"]
    for message in recent:
        content = " ".join(message.content.split())
        lines.append(f"{message.role}: {content[:260]}")
    return "\n".join(lines)


def graph_result_to_payload(result: Any) -> dict | None:
    """Convert GraphRetrievalResult dataclasses into a JSON-safe API payload."""

    if result is None:
        return None
    plan = getattr(result, "plan", None)
    facts = []
    for fact in getattr(result, "facts", []) or []:
        evidences = []
        for evidence in getattr(fact, "evidence", []) or []:
            evidences.append({
                "doc_short": getattr(evidence, "doc_short", ""),
                "doc_name": getattr(evidence, "doc_name", None),
                "pdf_filename": getattr(evidence, "pdf_filename", None),
                "page_start": getattr(evidence, "page_start", None),
                "page_end": getattr(evidence, "page_end", None),
                "chunk_id": getattr(evidence, "chunk_id", None),
                "source_version": getattr(evidence, "source_version", None),
                "confidence": getattr(evidence, "confidence", None),
            })
        facts.append({
            "subject": getattr(fact, "subject", ""),
            "relation": getattr(fact, "relation", ""),
            "object": getattr(fact, "object", None),
            "confidence": getattr(fact, "confidence", None),
            "status": getattr(fact, "status", "candidate"),
            "evidence": evidences,
            "properties": dict(getattr(fact, "properties", {}) or {}),
        })

    return {
        "plan": {
            "intents": list(getattr(plan, "intents", []) or []),
            "procedure_name": getattr(plan, "procedure_name", None),
            "category": getattr(plan, "category", None),
            "grade_system": getattr(plan, "grade_system", None),
            "requested_grade": getattr(plan, "requested_grade", None),
            "requested_peer_count": getattr(plan, "requested_peer_count", None),
        },
        "facts": facts,
        "source_chunk_ids": list(getattr(result, "source_chunk_ids", []) or []),
        "warnings": list(getattr(result, "warnings", []) or []),
    }


async def prepare_quickcode_context(query: str):
    """Build strict table-backed context for quickcode mode."""

    matched_row: dict | None = None
    row_type = "not_found"
    for term in extract_structured_terms(query):
        matched_row = _TABLE_STORE.lookup_surgery_grade(term)
        if matched_row:
            row_type = "surgery_grade"
            break
        matched_row = _TABLE_STORE.lookup_disability_rate(term)
        if matched_row:
            row_type = "disability_rate"
            break

    if not matched_row:
        prompt = (
            "[정형 매핑 데이터]\n"
            "일치하는 수술종수 또는 장해율 정형 테이블 행을 찾지 못했습니다.\n\n"
            f"[사용자 질문]\n{query}"
        )
        return [], [], prompt, QUICKCODE_SYSTEM_PROMPT

    table_context = _format_table_row(matched_row, row_type)
    source = {
        "filename": matched_row.get("source_file") or "정형 테이블",
        "doc_short": "정형테이블",
        "page": matched_row.get("source_page_label"),
        "chunk_id": f"structured-{row_type}",
        "snippet": table_context[:180],
        "table_type": row_type,
    }
    prompt = (
        f"{table_context}\n\n"
        f"[사용자 질문]\n{query}\n\n"
        "위 표의 수치와 조건을 그대로 사용해 답변하세요. 표에 없는 값은 추측하지 마세요."
    )
    return [], [source], prompt, QUICKCODE_SYSTEM_PROMPT


def formal_doc_filter(filters: dict | None) -> list[str] | None:
    """Translate formal-mode filters into doc_short filters."""

    filters = filters or {}
    explicit = filters.get("doc_filter") or filters.get("doc_short")
    if isinstance(explicit, str):
        return [explicit]
    if isinstance(explicit, list):
        return [str(item) for item in explicit if item]

    category = filters.get("product_category")
    if category is None:
        return ["약관"]
    return _PRODUCT_DOC_FILTERS.get(str(category), ["약관"])


async def prepare_formal_context(
    pipeline: RagPipeline,
    question: str,
    top_k: int,
    history: list[ChatMessage],
    filters: dict | None,
    memo: str | None = None,
):
    """Build formal-mode context with a forced metadata/doc filter."""

    doc_filter = formal_doc_filter(filters)
    hits, _ = pipeline.retrieve_hits(question, top_k=top_k, doc_filter=doc_filter)
    chunks = [_hit_to_chunk(hit) for hit in hits]
    sources = [chunk_to_source(chunk) for chunk in chunks]
    prompt_question = question
    if memo:
        prompt_question = f"{question}\n\n[상황 메모]\n{memo.strip()}"
    prompt = pipeline.build_prompt(prompt_question, chunks)
    history_context = build_history_context(history)
    if history_context:
        prompt = f"{history_context}\n\n{prompt}"
    return chunks, sources, prompt, doc_filter


def finalize_answer(raw_answer: str, chunks: list) -> str:
    """Apply source citations to a generated answer."""

    return finalize_answer_for_question("", raw_answer, chunks)


def finalize_answer_for_question(question: str, raw_answer: str, chunks: list) -> str:
    """Apply source citations and evidence validation warnings to a generated answer."""

    answer = append_retrieved_source_citations(raw_answer.strip(), chunks)
    return append_evidence_validation_warning(answer, question, chunks)


__all__ = [
    "SYSTEM_PROMPT",
    "build_contextual_prompt",
    "chunk_to_source",
    "finalize_answer",
    "finalize_answer_for_question",
    "formal_doc_filter",
    "graph_result_to_payload",
    "get_rag_pipeline",
    "build_history_context",
    "prepare_formal_context",
    "prepare_quickcode_context",
    "prepare_retrieved_context",
    "summarize_legacy_messages",
]
