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
from src.retrieval.chunk_lookup import ChunkLookupRef
from src.retrieval.embedder import Embedder
from src.retrieval.index_mode import INDEX_MODES, resolve_effective_index_mode, resolve_index_paths
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
    clarification: dict | None = None,
):
    """Retrieve chunks, GraphDB facts, source metadata, and a prompt for generation."""

    graph_result = None
    graph_context = ""
    graph_hits = []
    warnings: list[dict[str, str]] = []

    if getattr(pipeline, "graph_enabled", False) and getattr(pipeline, "graph_retriever", None):
        try:
            graph_result = pipeline.graph_retriever.retrieve(question, clarification=clarification)
            graph_context = build_graph_context(graph_result)
            source_chunk_ids = getattr(graph_result, "source_chunk_ids", []) or []
            source_chunk_refs = getattr(graph_result, "source_chunk_refs", []) or []
            if source_chunk_refs:
                graph_hits = pipeline.vector_store.get_by_refs(source_chunk_refs)
            elif source_chunk_ids:
                graph_hits = pipeline.vector_store.get_by_ids(source_chunk_ids)
            found_ids = {hit.id for hit in graph_hits}
            missing_ids = [chunk_id for chunk_id in source_chunk_ids if chunk_id not in found_ids]
            if missing_ids:
                logger.info(
                    "GraphDB source chunks are not present in current VectorStore: %s",
                    ", ".join(missing_ids[:5]),
                )
        except Exception as exc:  # pragma: no cover - runtime fallback
            logger.warning("Graph retrieval failed in API path: %s", exc, exc_info=True)
            warnings.append({
                "code": "GRAPH_RETRIEVAL_FAILED",
                "message": "GraphDB 근거 조회 중 오류가 발생해 일반 RAG로 답변합니다.",
            })
            graph_result = None
            graph_context = ""
            graph_hits = []

    hits, debug = pipeline.retrieve_hits(question, top_k=top_k, graph_hits=graph_hits, return_debug=True)
    chunks = [_hit_to_chunk(hit) for hit in hits]
    sources = [chunk_to_source(chunk) for chunk in chunks]
    prompt = pipeline.build_prompt(question, chunks, graph_context=graph_context)
    history_context = build_history_context(history)
    if history_context:
        prompt = f"{history_context}\n\n{prompt}"
    deterministic_answer = _deterministic_guard_answer(question, chunks, graph_context=graph_context)
    if debug is not None:
        debug.graph_result = graph_result
    return chunks, sources, prompt, graph_result_to_payload(graph_result), warnings, deterministic_answer, debug


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


def graph_review_status_label(status: str) -> str:
    return {
        "confirmed": "확정 근거",
        "review_required": "검토 필요",
        "candidate": "검토 후보",
        "missing": "구조화 근거 없음",
    }.get(status or "", status or "검토 필요")


def graph_review_path_type_label(path_type: str) -> str:
    return {
        "complication_review": "합병증/후유증 검토",
        "diagnosis_review": "진단코드 검토",
        "procedure_policy_review": "수술/약관 검토",
        "claim_condition_review": "청구 조건 검토",
        "claim_calculation_review": "보험금 계산 검토",
        "coordination_review": "중복 보상 조정 검토",
        "generation_rule_review": "세대/갱신 기준 검토",
        "one_disease_review": "하나의 질병 검토",
        "disease_grouping_review": "질병 묶음 기준 검토",
        "claim_unit_limit_review": "보상 단위/한도 검토",
        "same_disease_surgery_review": "동일 질병 수술비 검토",
        "recurrent_treatment_review": "반복/계속 치료 검토",
    }.get(path_type or "", path_type or "구조화 검토")


def graph_result_to_payload(result: Any) -> dict | None:
    """Convert GraphRetrievalResult dataclasses into a JSON-safe API payload."""

    if result is None:
        return None
    plan = getattr(result, "plan", None)
    source_chunk_refs = list(getattr(result, "source_chunk_refs", []) or [])
    if not source_chunk_refs:
        source_chunk_refs = _collect_payload_source_chunk_refs(result)
    facts = []
    review_paths = []
    session_assertions = []
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
                "canonical_chunk_id": getattr(evidence, "canonical_chunk_id", None),
                "source_chunk_id": getattr(evidence, "source_chunk_id", None),
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

    for assertion in getattr(result, "session_assertions", []) or []:
        session_assertions.append({
            "kind": getattr(assertion, "kind", ""),
            "value": getattr(assertion, "value", ""),
            "source": getattr(assertion, "source", "question"),
            "confidence": getattr(assertion, "confidence", 1.0),
            "notes": getattr(assertion, "notes", ""),
        })

    for path in getattr(result, "review_paths", []) or []:
        steps = []
        for step in getattr(path, "steps", []) or []:
            evidences = []
            for evidence in getattr(step, "evidence", []) or []:
                evidences.append({
                    "doc_short": getattr(evidence, "doc_short", ""),
                    "page_start": getattr(evidence, "page_start", None),
                    "page_end": getattr(evidence, "page_end", None),
                    "chunk_id": getattr(evidence, "chunk_id", None),
                    "canonical_chunk_id": getattr(evidence, "canonical_chunk_id", None),
                    "source_chunk_id": getattr(evidence, "source_chunk_id", None),
                })
            steps.append({
                "source": getattr(step, "source", ""),
                "subject": getattr(step, "subject", ""),
                "relation": getattr(step, "relation", ""),
                "object": getattr(step, "object", None),
                "status": getattr(step, "status", "candidate"),
                "evidence": evidences,
                "notes": getattr(step, "notes", ""),
            })
        review_paths.append({
            "path_id": getattr(path, "path_id", ""),
            "path_type": getattr(path, "path_type", ""),
            "path_type_label": graph_review_path_type_label(getattr(path, "path_type", "")),
            "steps": steps,
            "status": getattr(path, "status", "missing"),
            "status_label": graph_review_status_label(getattr(path, "status", "missing")),
            "summary": getattr(path, "summary", ""),
            "required_evidence": list(getattr(path, "required_evidence", []) or []),
            "review_actions": list(getattr(path, "review_actions", []) or []),
            "exclusion_reasons": list(getattr(path, "exclusion_reasons", []) or []),
            "benefit_limits": list(getattr(path, "benefit_limits", []) or []),
            "deductible_rules": list(getattr(path, "deductible_rules", []) or []),
            "required_documents": list(getattr(path, "required_documents", []) or []),
            "coordination_rules": list(getattr(path, "coordination_rules", []) or []),
            "generation_rules": list(getattr(path, "generation_rules", []) or []),
        })

    rule_payload = {
        "exclusion_reasons": sorted({item for path in review_paths for item in path.get("exclusion_reasons", [])}),
        "benefit_limits": sorted({item for path in review_paths for item in path.get("benefit_limits", [])}),
        "deductible_rules": sorted({item for path in review_paths for item in path.get("deductible_rules", [])}),
        "required_documents": sorted({item for path in review_paths for item in path.get("required_documents", [])}),
        "coordination_rules": sorted({item for path in review_paths for item in path.get("coordination_rules", [])}),
        "generation_rules": sorted({item for path in review_paths for item in path.get("generation_rules", [])}),
    }

    return {
        "plan": {
            "intents": list(getattr(plan, "intents", []) or []),
            "procedure_name": getattr(plan, "procedure_name", None),
            "category": getattr(plan, "category", None),
            "grade_system": getattr(plan, "grade_system", None),
            "grade_value": getattr(plan, "grade_value", None),
            "requested_peer_count": getattr(plan, "requested_peer_count", None),
            "diagnosis_codes": list(getattr(plan, "diagnosis_codes", []) or []),
            "coverage_topics": list(getattr(plan, "coverage_topics", []) or []),
            "conditions": list(getattr(plan, "conditions", []) or []),
            "complication_asserted": getattr(plan, "complication_asserted", False),
            "treatment_purpose": getattr(plan, "treatment_purpose", None),
            "evidence_tags": list(getattr(plan, "evidence_tags", []) or []),
            "policy_generation": getattr(plan, "policy_generation", None),
            "visit_type": getattr(plan, "visit_type", None),
            "facility_type": getattr(plan, "facility_type", None),
            "one_disease_terms": list(getattr(plan, "one_disease_terms", []) or []),
            "claim_unit_terms": list(getattr(plan, "claim_unit_terms", []) or []),
            "disease_grouping_requested": getattr(plan, "disease_grouping_requested", False),
            "same_disease_claimed": getattr(plan, "same_disease_claimed", False),
            "same_treatment_purpose_claimed": getattr(plan, "same_treatment_purpose_claimed", False),
            "recurrent_or_continuing_treatment": getattr(plan, "recurrent_or_continuing_treatment", False),
            "newly_found_disease_claimed": getattr(plan, "newly_found_disease_claimed", False),
            "normalized_terms": dict(getattr(plan, "normalized_terms", {}) or {}),
            "term_correction_candidates": list(getattr(plan, "term_correction_candidates", []) or []),
            "ambiguous_terms": list(getattr(plan, "ambiguous_terms", []) or []),
            "clarification_questions": list(getattr(plan, "clarification_questions", []) or []),
        },
        "facts": facts,
        "session_assertions": session_assertions,
        "graph_review_paths": review_paths,
        "required_evidence": list(getattr(result, "required_evidence", []) or []),
        "review_actions": list(getattr(result, "review_actions", []) or []),
        **rule_payload,
        "source_chunk_ids": list(getattr(result, "source_chunk_ids", []) or []),
        "source_chunk_refs": [
            {
                "requested_id": getattr(ref, "requested_id", ""),
                "canonical_chunk_id": getattr(ref, "canonical_chunk_id", None),
                "source_chunk_id": getattr(ref, "source_chunk_id", None),
                "doc_short": getattr(ref, "doc_short", None),
                "page_start": getattr(ref, "page_start", None),
                "page_end": getattr(ref, "page_end", None),
            }
            for ref in source_chunk_refs
        ],
        "warnings": list(getattr(result, "warnings", []) or []),
    }


def _collect_payload_source_chunk_refs(result: Any) -> list[ChunkLookupRef]:
    refs: list[ChunkLookupRef] = []
    seen: set[tuple[str, str | None, str | None, str | None, int | None, int | None]] = set()

    def _append(evidence: Any) -> None:
        requested_id = getattr(evidence, "chunk_id", None)
        if not requested_id:
            return
        ref = ChunkLookupRef(
            requested_id=requested_id,
            canonical_chunk_id=getattr(evidence, "canonical_chunk_id", None),
            source_chunk_id=getattr(evidence, "source_chunk_id", None),
            doc_short=getattr(evidence, "doc_short", None),
            page_start=getattr(evidence, "page_start", None),
            page_end=getattr(evidence, "page_end", None),
        )
        key = (
            ref.requested_id,
            ref.canonical_chunk_id,
            ref.source_chunk_id,
            ref.doc_short,
            ref.page_start,
            ref.page_end,
        )
        if key in seen:
            return
        seen.add(key)
        refs.append(ref)

    for fact in getattr(result, "facts", []) or []:
        for evidence in getattr(fact, "evidence", []) or []:
            _append(evidence)
    for path in getattr(result, "review_paths", []) or []:
        for step in getattr(path, "steps", []) or []:
            for evidence in getattr(step, "evidence", []) or []:
                _append(evidence)
    return refs


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
