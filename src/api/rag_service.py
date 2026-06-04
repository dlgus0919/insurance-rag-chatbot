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
from src.rag.quick_code import build_quick_code_prompt, retrieve_quick_code_chunks
from src.rag.table_store import TableStore
from src.retrieval.bm25 import BM25Index
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
_FORMAL_CATEGORY_DOC_FILTERS = {
    "실손": ["약관", "표준약관"],
    "3대비급여": ["약관", "표준약관"],
    "암보험": ["자사_SOL건강"],
}
_EMBEDDED_REVIEW_TEMPLATE_MARKERS = (
    "■ 섹션 1",
    "섹션 1️⃣",
    "【확정 근거】",
)
_EMBEDDED_REVIEW_SECTION_PATTERN = re.compile(r"^\s*■\s*섹션\s*\d")
_EMBEDDED_REVIEW_HEADING_PATTERN = re.compile(r"^\s*【[^】]+】\s*$")
_EMBEDDED_REVIEW_BULLET_PATTERN = re.compile(r"^\s*(?:[-*•]\s+|☐\s*|→\s*\d+\.\s*|→\s*)")
_SOURCE_CITATION_LINE_PATTERN = re.compile(r"^\s*\[출처:\s*.+\]\s*$")
_TRAILING_SOURCE_NOTE_PATTERN = re.compile(r"^\s*\(참고:\s*.+\)\s*$")


@lru_cache(maxsize=1)
def _load_shared_retrieval_components():
    embedder = Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
    reranker = build_reranker(enabled=config.RERANKER_ENABLED)
    return embedder, reranker


@lru_cache(maxsize=4)
def _load_index_retrieval_components(index_mode: str):
    bm25_path, chroma_dir = _resolve_index_paths(index_mode)
    if not bm25_path.exists():
        raise RuntimeError(
            f"BM25 인덱스가 없습니다: {bm25_path}. "
            "`python scripts/ingest.py --stage index`를 먼저 실행하세요."
        )
    vector_store = VectorStore(chroma_dir)
    bm25 = BM25Index.load(bm25_path)
    return vector_store, bm25


@lru_cache(maxsize=16)
def get_rag_pipeline(
    model: str,
    top_k: int,
    index_mode: str = "default",
) -> RagPipeline:
    """Build a cached RAG pipeline for API requests."""

    embedder, reranker = _load_shared_retrieval_components()
    vector_store, bm25 = _load_index_retrieval_components(index_mode)
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
    filters: dict | None = None,
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

    doc_filter = extract_doc_filter(filters)
    hits, debug = pipeline.retrieve_hits(
        question,
        top_k=top_k,
        doc_filter=doc_filter,
        graph_hits=graph_hits,
        return_debug=True,
    )
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


def extract_doc_filter(filters: dict | None) -> list[str] | None:
    """Normalize requested doc_short filters from frontend payloads."""

    filters = filters or {}
    explicit = filters.get("doc_filter") or filters.get("doc_short")
    if isinstance(explicit, str):
        explicit = [explicit]
    if not isinstance(explicit, list):
        return None
    values = [str(item).strip() for item in explicit if str(item).strip()]
    return list(dict.fromkeys(values)) or None


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
    }.get(path_type or "", path_type or "구조화 검토")


_CONFIRMED_DIAGNOSIS_EXCLUSION_REASON = "약관상 보상제외 치료"
_EXCLUSION_RESOLVED_CLARIFICATION_KEYWORDS = (
    "실손 세대",
    "입원/통원",
    "처방조제",
    "방문 구분",
    "진료비 영수증",
    "진료비 세부내역서",
    "진단서",
    "증빙",
)
_EXCLUSION_RESOLVED_AMBIGUOUS_TERMS = {"실손 세대", "방문 구분", "증빙 서류"}


def _has_confirmed_diagnosis_exclusion_path(review_paths: list[dict]) -> bool:
    for path in review_paths:
        if path.get("path_type") != "diagnosis_review":
            continue
        if path.get("status") != "confirmed":
            continue
        if _CONFIRMED_DIAGNOSIS_EXCLUSION_REASON in (path.get("exclusion_reasons") or []):
            return True
    return False


def _prune_clarification_for_confirmed_exclusion(plan_payload: dict, review_paths: list[dict]) -> None:
    """Do not ask generation/visit/evidence follow-ups after a direct exclusion is confirmed."""

    if not _has_confirmed_diagnosis_exclusion_path(review_paths):
        return

    plan_payload["clarification_questions"] = [
        question
        for question in plan_payload.get("clarification_questions", [])
        if not any(keyword in question for keyword in _EXCLUSION_RESOLVED_CLARIFICATION_KEYWORDS)
    ]
    plan_payload["ambiguous_terms"] = [
        term
        for term in plan_payload.get("ambiguous_terms", [])
        if term not in _EXCLUSION_RESOLVED_AMBIGUOUS_TERMS
    ]


def graph_result_to_payload(result: Any) -> dict | None:
    """Convert GraphRetrievalResult dataclasses into a JSON-safe API payload."""

    if result is None:
        return None
    plan = getattr(result, "plan", None)
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

    plan_payload = {
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
        "normalized_terms": dict(getattr(plan, "normalized_terms", {}) or {}),
        "term_correction_candidates": list(getattr(plan, "term_correction_candidates", []) or []),
        "ambiguous_terms": list(getattr(plan, "ambiguous_terms", []) or []),
        "clarification_questions": list(getattr(plan, "clarification_questions", []) or []),
    }
    _prune_clarification_for_confirmed_exclusion(plan_payload, review_paths)

    return {
        "plan": plan_payload,
        "facts": facts,
        "session_assertions": session_assertions,
        "graph_review_paths": review_paths,
        "required_evidence": list(getattr(result, "required_evidence", []) or []),
        "review_actions": list(getattr(result, "review_actions", []) or []),
        **rule_payload,
        "source_chunk_ids": list(getattr(result, "source_chunk_ids", []) or []),
        "warnings": list(getattr(result, "warnings", []) or []),
    }


async def prepare_quickcode_context(
    pipeline: RagPipeline,
    query: str,
    filters: dict | None = None,
):
    """Build quick-code retrieval context from UI options and requested scope."""

    filters = filters or {}
    include_summary = bool(filters.get("include_summary", True))
    include_coverage = bool(filters.get("include_coverage", True))
    selected_docs = extract_doc_filter(filters)

    chunks, applied_doc_filter = retrieve_quick_code_chunks(
        pipeline,
        query,
        include_coverage=include_coverage,
        selected_docs=selected_docs,
    )
    sources = [chunk_to_source(chunk) for chunk in chunks]
    system_prompt, prompt = build_quick_code_prompt(
        query,
        chunks,
        include_summary=include_summary,
        include_coverage=include_coverage,
    )
    if applied_doc_filter:
        prompt = f"[적용 문서 필터] {', '.join(applied_doc_filter)}\n\n{prompt}"
    return chunks, sources, prompt, system_prompt, applied_doc_filter


def formal_doc_filter(filters: dict | None) -> list[str] | None:
    """Translate formal-mode filters into doc_short filters."""

    filters = filters or {}
    merged: list[str] = []
    explicit = extract_doc_filter(filters)
    if explicit:
        merged.extend(explicit)

    category = filters.get("product_category")
    categories = category if isinstance(category, list) else [category] if category else []
    for item in categories:
        merged.extend(_FORMAL_CATEGORY_DOC_FILTERS.get(str(item), _PRODUCT_DOC_FILTERS.get(str(item), [])))

    return list(dict.fromkeys(merged or ["약관"]))


def build_formal_retrieval_query(question: str, filters: dict | None) -> str:
    """Shape the retrieval query to reflect the formal search intent."""

    search_type = ((filters or {}).get("search_type") or "").strip()
    normalized_question = question.strip()
    if not search_type or not normalized_question:
        return normalized_question

    if search_type == "약관 조문 검색":
        hint = "약관 조문 별표 보상내용 보상하지 않는 사항 보험금 지급"
    elif search_type == "키워드/시술명 검색":
        hint = "키워드 시술명 수술명 치료명 검사명"
    else:
        hint = "보상 가능 여부 판단 약관 기준 지급 제외"
    return f"{normalized_question}\n{hint}"


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
    retrieval_query = build_formal_retrieval_query(question, filters)
    hits, _ = pipeline.retrieve_hits(retrieval_query, top_k=top_k, doc_filter=doc_filter)
    chunks = [_hit_to_chunk(hit) for hit in hits]
    sources = [chunk_to_source(chunk) for chunk in chunks]
    prompt_blocks: list[str] = []
    search_type = (filters or {}).get("search_type")
    if search_type:
        prompt_blocks.append(f"[검색 유형]\n{search_type}")
    product_category = (filters or {}).get("product_category")
    if product_category:
        if isinstance(product_category, list):
            names = ", ".join(str(item) for item in product_category if item)
        else:
            names = str(product_category)
        if names:
            prompt_blocks.append(f"[선택 시나리오]\n{names}")
    prompt_blocks.append(question)
    prompt_question = "\n\n".join(prompt_blocks)
    if memo:
        prompt_question = f"{prompt_question}\n\n[상황 메모]\n{memo.strip()}"
    prompt = pipeline.build_prompt(prompt_question, chunks)
    history_context = build_history_context(history)
    if history_context:
        prompt = f"{history_context}\n\n{prompt}"
    return chunks, sources, prompt, doc_filter


def finalize_answer(raw_answer: str, chunks: list) -> str:
    """Apply source citations to a generated answer."""

    return finalize_answer_for_question("", raw_answer, chunks)


def strip_embedded_review_template(raw_answer: str) -> str:
    """Remove model-written review template blocks so frontend can render authoritative panels."""

    text = raw_answer.strip()
    if not text:
        return ""

    cut_positions = [text.find(marker) for marker in _EMBEDDED_REVIEW_TEMPLATE_MARKERS if text.find(marker) >= 0]
    if not cut_positions:
        return text

    cut_index = min(cut_positions)
    leading = text[:cut_index].rstrip()
    if not leading:
        answer_marker = text.find("[답변]")
        if answer_marker >= 0:
            extracted = text[answer_marker + len("[답변]"):].strip()
            return extracted or text
        return _summarize_embedded_review_template(text)
    return leading


def _summarize_embedded_review_template(text: str) -> str:
    """Collapse a pure review-template body into a concise user-facing summary."""

    candidates: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.replace("\u00a0", " ").strip()
        if not line:
            continue
        if line.startswith("[출처:"):
            continue
        if _EMBEDDED_REVIEW_SECTION_PATTERN.match(line):
            continue
        if _EMBEDDED_REVIEW_HEADING_PATTERN.match(line):
            continue
        if line == "해당 없음":
            continue
        if "Graph review path" in line:
            continue
        if line.startswith("⚠️"):
            continue
        if line.startswith("➜"):
            continue
        if "현황:" in line and "중요도:" in line:
            continue

        cleaned = _EMBEDDED_REVIEW_BULLET_PATTERN.sub("", line).strip()
        if not cleaned:
            continue
        if cleaned not in candidates:
            candidates.append(cleaned)

    if not candidates:
        return "제공된 구조화 검토 경로 기준으로 추가 확인이 필요합니다."

    summary = " ".join(candidates[:3]).strip()
    summary = re.sub(r"\s+", " ", summary)
    if summary and summary[-1] not in ".!?":
        summary += "."
    return summary


def strip_trailing_source_citation_lines(text: str) -> str:
    """Remove only trailing source-only blocks rendered separately by the UI/export."""

    lines = text.strip().splitlines()
    if not lines:
        return ""

    end = len(lines)
    note_removed = False
    while end > 0:
        line = lines[end - 1].strip()
        if not line:
            end -= 1
            continue
        if _SOURCE_CITATION_LINE_PATTERN.match(line):
            end -= 1
            continue
        if not note_removed and _TRAILING_SOURCE_NOTE_PATTERN.match(line):
            note_removed = True
            end -= 1
            continue
        break

    cleaned = "\n".join(line.rstrip() for line in lines[:end]).strip()
    return cleaned or text.strip()


def normalize_assistant_answer_for_display(text: str) -> str:
    """Normalize stored/generated assistant text for UI and export display."""

    return strip_trailing_source_citation_lines(strip_embedded_review_template(text))


def finalize_answer_for_question(question: str, raw_answer: str, chunks: list) -> str:
    """Apply source citations and evidence validation warnings to a generated answer."""

    answer = append_retrieved_source_citations(strip_embedded_review_template(raw_answer), chunks)
    answer = append_evidence_validation_warning(answer, question, chunks)
    return normalize_assistant_answer_for_display(answer)


__all__ = [
    "SYSTEM_PROMPT",
    "build_contextual_prompt",
    "chunk_to_source",
    "finalize_answer",
    "finalize_answer_for_question",
    "formal_doc_filter",
    "graph_result_to_payload",
    "get_rag_pipeline",
    "normalize_assistant_answer_for_display",
    "build_history_context",
    "prepare_formal_context",
    "prepare_quickcode_context",
    "prepare_retrieved_context",
    "strip_embedded_review_template",
    "summarize_legacy_messages",
]
