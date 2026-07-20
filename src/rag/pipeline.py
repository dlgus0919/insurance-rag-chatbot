"""검색과 LLM 생성을 연결하는 RAG 파이프라인."""

from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from src import config
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.ontology.registry import get_default_ontology_registry
from src.parser.chunker import Chunk
from src.rag.auto_params import AutoRagParams, apply_adaptive_k_to_hits
from src.rag.clause_detail_rows import ClauseDetailRowRecord, ClauseDetailRowStore
from src.rag.evidence import append_evidence_validation_warning, build_strict_evidence_context, detect_retrieval_conflicts
from src.rag.evidence_assessment import evaluate_registry_evidence
from src.rag.search_intent import SearchIntentPlan, classify_search_intent, extract_code_terms
from src.rag.source_grounded_answers import (
    build_absent_code_guard_answer,
    build_generation_deductible_comparison_answer,
    build_hira_fee_answer,
)
from src.rag.procedure_grade import format_procedure_grade_answer, resolve_procedure_grade
from src.rag.table_store import TableStore
from src.retrieval import Hit
from src.retrieval.chunk_lookup import graph_chunk_fallback_ids
from src.retrieval.hybrid import rrf_fuse
from src.retrieval.reranker import RerankResult, build_reranker
try:
    from src.graph.retriever import GraphRetriever
    from src.graph.context import build_graph_context
    _GRAPH_IMPORT_OK = True
except ImportError:
    _GRAPH_IMPORT_OK = False



_CODE_PATTERN = re.compile(r"(?<![A-Z0-9.])(?:[A-Z]\d{2}(?:\.\d{1,2})?|[A-Z]{1,3}\d{2,5})(?![A-Z0-9.])")
_SURGERY_QUERY_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9 ·∙/()_-]{3,})\s*의\s*(?:[^?]{0,40}?)?(?:수술종수|수술해설|수술방법|수술 방법|수술종류|수술 종류|분류)",
    re.UNICODE,
)
_SURGERY_GRADE_COLUMN_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9 ·∙/()_-]{3,})\s*의\s*(?:1-3종|1-5종|신1-5종)",
    re.UNICODE,
)
_SURGERY_DESC_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9 ·∙/()_-]{3,})\s*(?:은|이란)\s*(?:어떤|무엇)",
    re.UNICODE,
)
_DISABILITY_KEYWORDS = [
    "두 눈",
    "한 눈",
    "두 귀",
    "한 귀",
    "코",
    "척추",
    "두 팔",
    "한 팔",
    "두 다리",
    "한 다리",
    "두 손",
    "한 손",
    "손가락",
    "발가락",
    "씹어먹는",
    "말하는 기능",
]
_DISABILITY_QUERY_PATTERN = re.compile(
    r"(.{2,15}?)\s*(?:을|를)\s*(?:완전히\s*)?(?:잃었을 때|상실)",
    re.UNICODE,
)
_DISABILITY_DESC_PATTERN = re.compile(
    r"(.{2,20}?)\s*(?:장해|운동장해|기능장해)\s*(?:가|이)\s*남은",
    re.UNICODE,
)
_DISABILITY_RATE_QUESTION_PATTERN = re.compile(
    r"^(.{4,60}?)\s*(?:장해\s*)?지급률",
    re.UNICODE,
)
_OLD_SURGERY_TABLE_MARKERS = ("수술종류분류", "종류분류(종)", "수술분류표")
_DOC_COMPARE_TERMS = ("문서별", "각각", "비교", "차이", "출처별", "기준별")
_DOC_ALIASES: dict[str, tuple[str, ...]] = {
    "심평원": ("심평원", "건강보험 고시", "급여 상대가치점수"),
    "약관": ("실손의료보험 약관", "이지로운 실손", "질병급여", "질병비급여", "3대비급여"),
    "자사_SOL건강": ("자사 SOL건강", "자사SOL건강", "SOL건강", "처음건강보험", "건강보험 약관"),
    "자사_SOL운전자": ("자사 SOL운전자", "자사SOL운전자", "SOL운전자", "처음운전자보험", "운전자보험 약관"),
    "표준약관": ("표준약관",),
    "실무가이드": ("실무가이드", "실무종합가이드", "Claim 실무"),
    "상담사례집": ("상담사례집", "소비자 상담", "상담 주요 사례"),
}
_CLAUSE_DETAIL_QUERY_CUES = (
    "진단확정",
    "확정기준",
    "진단기준",
    "필요서류",
    "필요한서류",
    "청구서류",
    "제출서류",
    "구비서류",
    "자기부담금",
    "자기부담",
    "보상한도",
    "보장한도",
    "지급한도",
    "연간한도",
    "횟수한도",
    "보장기간",
    "지급기간",
)
_FALLBACK_CLAUSE_DETAIL_CONTEXT_TERMS = {
    "diagnosis": ("진단확정", "정의 및 진단확정", "병력", "신경학적 검진", "CT", "MRI", "의사"),
    "documents": ("보험금의 청구", "청구서", "사고증명서", "진단서", "신분증", "구비서류", "제출서류"),
    "deductible": (
        "자기부담금",
        "자기부담",
        "공제금액",
        "공제",
        "보장대상의료비",
        "보험금 등의 지급한도",
        "지급한도",
        "대물",
        "대인",
    ),
    "limit": (
        "보험금 등의 지급한도",
        "보상한도",
        "보장한도",
        "지급한도",
        "연간",
        "1년 단위",
        "횟수",
        "보장기간",
        "지급기간",
    ),
}
_CLAUSE_DETAIL_NUMBER_PATTERN = re.compile(
    r"\d+\s*[~∼-]\s*\d+\s*(?:만원|원|%|회|년|세)|"
    r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|만원|원|회|년|세)"
)
_CLAUSE_DETAIL_ARTICLE_PATTERN = re.compile(r"제\s*\d+\s*조|[<＜]\s*표\s*\d+\s*[>＞]|표\s*\d+")
_CLAUSE_DETAIL_ROW_BOUNDARY_PATTERN = re.compile(
    r"(?=(?:[-•]\s*)?(?:3대\s*비급여|3대비급여|비급여|급여|상해|질병)\s*[\(（])|"
    r"(?=(?:[-•]\s*)?(?:입원|통원|외래|처방조제)\s*(?:치료|의료비|비|1회))"
)
_CLAUSE_DETAIL_ROW_SPLIT_AFTER_PATTERN = re.compile(
    r"((?:%|만원|원|큰 금액|공제|보상|제출해야 합니다|확인원))\s+"
)
_CLAUSE_DETAIL_PREFIX_PATTERN = re.compile(r"(?:3대\s*비급여|3대비급여|비급여|급여|상해|질병)\s*[\(（]")
_CLAUSE_DETAIL_CONTEXT_RESET_TERMS = ("입원", "통원", "외래", "처방조제")
_CLAUSE_DETAIL_FACET_GROUPS = (
    ("3대비급여", "비급여", "급여"),
    ("상해", "질병"),
    ("입원", "통원", "외래", "처방조제"),
    ("1회", "자기부담금", "자기부담", "공제금액", "공제", "보상비율", "보상", "지급한도", "필요서류", "청구서류", "진단확정"),
)
_CLAUSE_DETAIL_REQUIRED_FACET_GROUPS = (
    ("입원", "통원", "외래", "처방조제"),
    ("1회",),
)
_CLAUSE_DETAIL_FALLBACK_SCORING = {
    "facet": 3,
    "category_keyword": 2,
    "number": 3,
    "article": 1,
    "source_label": 4,
    "table_row": 5,
    "min_score": 5,
}
_HIRA_CHUNKS_PATH = Path("data/processed/chunks.jsonl")
_HIRA_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "췌장 이식수술": ("췌이식술", "췌장이식술"),
    "간장 이식수술": ("간이식술", "간장이식술"),
}
_HIRA_LOOKUP_TRIGGERS = ("수가코드", "수가", "심평원", "수가표", "점수", "수술코드", "hira")
_HIRA_FEE_CODE_PATTERN = re.compile(r"^[A-Z]{1,3}\d{3,5}$")
_HIRA_TERM_PATTERN = re.compile(r"[가-힣A-Za-z0-9·∙/()_-]{1,24}(?:이식수술|이식술|수술|절제술|폐쇄술|치료|검사)")
_HIRA_CHUNK_CACHE: list[dict] | None = None


@lru_cache(maxsize=4)
def _load_clause_detail_policy(path_value: str) -> dict[str, Any]:
    """Load clause detail row matching policy from JSON."""

    if not path_value:
        return {}
    policy_path = Path(path_value)
    if not policy_path.exists():
        return {}
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _clause_detail_policy() -> dict[str, Any]:
    return _load_clause_detail_policy(str(config.CLAUSE_DETAIL_POLICY_PATH))


def _clause_detail_pattern(name: str, fallback: re.Pattern[str]) -> re.Pattern[str]:
    raw = _clause_detail_policy().get(name)
    if not isinstance(raw, str) or not raw:
        return fallback
    try:
        return re.compile(raw)
    except re.error:
        return fallback


def _clause_detail_policy_groups(name: str, fallback: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
    raw = _clause_detail_policy().get(name)
    if not isinstance(raw, list):
        return fallback
    groups: list[tuple[str, ...]] = []
    for group in raw:
        if not isinstance(group, list):
            continue
        terms = tuple(str(term).strip() for term in group if str(term).strip())
        if terms:
            groups.append(terms)
    return tuple(groups) or fallback


def _clause_detail_policy_terms(name: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    raw = _clause_detail_policy().get(name)
    if not isinstance(raw, list):
        return fallback
    terms = tuple(str(term).strip() for term in raw if str(term).strip())
    return terms or fallback


def _clause_detail_context_terms(category: str) -> tuple[str, ...]:
    raw = _clause_detail_policy().get("category_context_terms")
    if isinstance(raw, dict):
        terms = raw.get(category)
        if isinstance(terms, list):
            normalized = tuple(str(term).strip() for term in terms if str(term).strip())
            if normalized:
                return normalized
    return _FALLBACK_CLAUSE_DETAIL_CONTEXT_TERMS.get(category, ())


def _clause_detail_score_weight(name: str) -> int:
    raw = _clause_detail_policy().get("scoring")
    if isinstance(raw, dict):
        try:
            return int(raw.get(name, _CLAUSE_DETAIL_FALLBACK_SCORING[name]))
        except (KeyError, TypeError, ValueError):
            return int(_CLAUSE_DETAIL_FALLBACK_SCORING.get(name, 0))
    return int(_CLAUSE_DETAIL_FALLBACK_SCORING.get(name, 0))


def _load_hira_chunks() -> list[dict]:
    """심평원 청크를 경량 캐시로 읽어 row-level 보강 검색에 사용한다."""

    global _HIRA_CHUNK_CACHE
    if _HIRA_CHUNK_CACHE is not None:
        return _HIRA_CHUNK_CACHE
    chunks: list[dict] = []
    try:
        with _HIRA_CHUNKS_PATH.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                metadata = record.get("metadata") or {}
                if metadata.get("doc_short") != "심평원":
                    continue
                chunks.append(record)
    except Exception:
        chunks = []
    _HIRA_CHUNK_CACHE = chunks
    return chunks


def _extract_hira_lookup_terms(question: str, graph_context: str | None = None) -> tuple[list[str], list[str]]:
    """질문/Graph context에서 심평원 수가표 직접 조회용 코드와 시술명을 추출한다."""

    combined = f"{question}\n{graph_context or ''}"
    codes = _extract_hira_fee_codes(question)
    terms: list[str] = []
    for match in _HIRA_TERM_PATTERN.finditer(combined):
        term = match.group(0).strip(" .,:;()[]")
        if term in {"수술", "이식수술", "치료", "검사"}:
            continue
        if term and term not in terms:
            terms.append(term)
        for alias in _HIRA_TERM_ALIASES.get(term, ()):
            if alias not in terms:
                terms.append(alias)
    for source, aliases in _HIRA_TERM_ALIASES.items():
        if source in combined:
            for alias in aliases:
                if alias not in terms:
                    terms.append(alias)
    return codes, terms


def _has_explicit_hira_fee_intent(question: str) -> bool:
    """사용자 질문에 심평원 수가표 직접 조회 의도가 있는지 판별한다."""

    normalized_question = str(question or "").replace(" ", "").casefold()
    return bool(_extract_hira_fee_codes(question)) or any(
        trigger in normalized_question for trigger in _HIRA_LOOKUP_TRIGGERS
    )


def _extract_relevant_hira_lines(text: str, codes: list[str], terms: list[str]) -> list[str]:
    """매칭된 코드/시술명 주변 줄만 압축해 프롬프트에 넣는다."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    selected: list[str] = []
    normalized_terms = [_normalize_surgery_match_text(term) for term in terms]
    upper_codes = {code.upper() for code in codes}
    for idx, line in enumerate(lines):
        compact_line = _normalize_surgery_match_text(line)
        has_term = any(term and term in compact_line for term in normalized_terms)
        has_code = any(code in line.upper() for code in upper_codes)
        if not has_term and not has_code:
            continue
        for near_idx in range(idx, min(len(lines), idx + 4)):
            near_line = lines[near_idx]
            if near_line not in selected:
                selected.append(near_line)
    return selected[:8]


def _build_hira_fee_context(question: str, graph_context: str | None = None) -> str | None:
    """HIRA 수가/점수 질의에서 chunk 검색 실패를 보완하는 직접 조회 컨텍스트."""

    if not _has_explicit_hira_fee_intent(question):
        return None
    codes, terms = _extract_hira_lookup_terms(question, graph_context)
    if not codes and not terms:
        return None
    term_norms = [_normalize_surgery_match_text(term) for term in terms]
    rows: list[tuple[int, int, str, list[str]]] = []
    for record in _load_hira_chunks():
        text = record.get("text", "")
        metadata = record.get("metadata") or {}
        compact_text = _normalize_surgery_match_text(text)
        matched_codes = [code for code in codes if code.upper() in text.upper()]
        matched_terms = [term for term, norm in zip(terms, term_norms) if norm and norm in compact_text]
        if not matched_codes and not matched_terms:
            continue
        relevant = _extract_relevant_hira_lines(text, matched_codes, matched_terms)
        if not relevant:
            continue
        page = metadata.get("page_start") or 0
        score = len(matched_codes) * 3 + len(matched_terms) * 2
        rows.append((score, int(page), metadata.get("source_file") or "심평원", relevant))
    if not rows:
        return None
    rows.sort(key=lambda item: (-item[0], item[1]))
    lines = [
        "[심평원 수가표 직접 조회]",
        "아래 행은 HIRA/심평원 표 원문에서 코드·시술명으로 직접 찾은 근거입니다. 수가코드·점수 답변은 이 행을 우선하세요.",
    ]
    for _, page, source_file, relevant in rows[:5]:
        lines.append(f"- {source_file} p.{page}: " + " / ".join(relevant))
    return "\n".join(lines)


@dataclass
class StageHit:
    """단일 검색 단계의 hit 정보."""

    chunk_id: str
    doc_short: str
    score: float
    page_start: int | None
    page_end: int | None
    text_preview: str
    rank: int | None = None


@dataclass
class DebugInfo:
    """RAG 단계별 중간 검색 결과."""

    dense_hits: list[StageHit]
    bm25_hits: list[StageHit]
    rrf_hits: list[StageHit]
    final_hits: list[StageHit]
    search_intent: SearchIntentPlan | None = None
    retrieval_execution: "RetrievalExecutionInfo | None" = None
    graph_result: Any = None
    reranker_scores: list[StageHit] = field(default_factory=list)
    auto_cutoff: Any = None


@dataclass
class RetrievalExecutionInfo:
    """검색 의도 계획이 실제 검색 단계에 어떻게 적용됐는지 기록한다."""

    dynamic_rrf_enabled: bool
    dynamic_rrf_mode: str
    applied_dense_weight: float
    applied_bm25_weight: float
    applied_top_k_dense: int
    applied_top_k_bm25: int
    dense_filtered_executed: bool = False
    dense_general_executed: bool = False
    bm25_executed: bool = False
    skipped_general_dense: bool = False
    fallback_reason: str = ""

    def to_payload(self) -> dict:
        return {
            "dynamic_rrf_enabled": self.dynamic_rrf_enabled,
            "dynamic_rrf_mode": self.dynamic_rrf_mode,
            "applied_dense_weight": round(float(self.applied_dense_weight), 3),
            "applied_bm25_weight": round(float(self.applied_bm25_weight), 3),
            "applied_top_k_dense": self.applied_top_k_dense,
            "applied_top_k_bm25": self.applied_top_k_bm25,
            "dense_filtered_executed": self.dense_filtered_executed,
            "dense_general_executed": self.dense_general_executed,
            "bm25_executed": self.bm25_executed,
            "skipped_general_dense": self.skipped_general_dense,
            "fallback_reason": self.fallback_reason,
        }


@dataclass
class RagAnswer:
    """RAG 답변 결과."""

    answer: str
    chunks: list[Chunk]
    timing: dict
    debug: DebugInfo | None = None


@dataclass(frozen=True)
class ClauseDetailEvidenceRow:
    """질문과 매칭된 조항·표 세부 근거 후보."""

    score: int
    text: str
    numbers: list[str]
    doc_short: str
    page_start: int | None
    page_end: int | None
    chunk_id: str
    section: str
    article: str = ""
    table_label: str = ""
    parent_heading: str = ""
    row_label: str = ""
    value_text: str = ""
    source_kind: str = "text"
    source_metadata: dict[str, Any] = field(default_factory=dict)


def _hit_to_chunk(hit: Hit) -> Chunk:
    metadata = dict(hit.metadata)
    metadata.setdefault("char_count", len(hit.document))
    return Chunk(id=hit.id, text=hit.document, metadata=metadata)


def _hits_to_stage(hits: list[Hit]) -> list[StageHit]:
    """검색 Hit 목록을 관리자 진단용 StageHit 목록으로 변환한다."""

    return [
        StageHit(
            chunk_id=hit.id,
            doc_short=hit.metadata.get("doc_short", ""),
            score=round(hit.score, 4),
            page_start=hit.metadata.get("page_start"),
            page_end=hit.metadata.get("page_end"),
            text_preview=hit.document[:100],
        )
        for hit in hits
    ]


def _rerank_results_to_stage(results: list[RerankResult]) -> list[StageHit]:
    """Reranker 점수 목록을 관리자 진단용 StageHit 목록으로 변환한다."""

    return [
        StageHit(
            chunk_id=result.hit.id,
            doc_short=result.hit.metadata.get("doc_short", ""),
            score=round(float(result.score), 4),
            page_start=result.hit.metadata.get("page_start"),
            page_end=result.hit.metadata.get("page_end"),
            text_preview=result.hit.document[:100],
            rank=result.rank,
        )
        for result in results
    ]


def _extract_query_codes(question: str) -> list[str]:
    """질문에서 의료 코드 패턴을 추출하고 순서를 보존해 중복 제거한다."""

    return extract_code_terms(question)


def _extract_hira_fee_codes(question: str) -> list[str]:
    """Return user-supplied fee-code shaped values, excluding ICD diagnosis codes."""

    return [
        code
        for code in _extract_query_codes(question)
        if _HIRA_FEE_CODE_PATTERN.fullmatch(code.upper())
    ]


def _expand_retrieval_query(question: str) -> str:
    """검색 안정성을 위해 명세 범위의 동의어를 보강한다."""
    return get_default_ontology_registry().expand_retrieval_query(question)


def _extract_named_code_terms(question: str) -> list[str]:
    """'식도조루술의 코드'처럼 명칭으로 코드를 묻는 질의의 핵심 명칭을 추출한다."""

    terms: list[str] = []
    for match in re.finditer(r"([가-힣A-Za-z0-9·∙/()_-]{2,})\s*의\s*코드", question):
        term = match.group(1).strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def _normalize_surgery_match_text(text: str) -> str:
    """수술명 비교를 위해 공백/기호를 제거한 정규화 문자열을 반환한다."""

    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(text)).lower()


def _extract_surgery_name_from_query(question: str) -> str | None:
    """수술명 관련 질의에서 핵심 수술명 문자열을 추출한다."""

    for pattern in (_SURGERY_QUERY_PATTERN, _SURGERY_DESC_PATTERN, _SURGERY_GRADE_COLUMN_PATTERN):
        match = pattern.search(question)
        if not match:
            continue
        candidate = match.group(1).strip()
        # 비수술 문항 오탐을 줄이기 위해 수술명 형태(...술)를 요구한다.
        if "술" in candidate:
            return candidate
    return None


def _extract_disability_region_from_query(question: str) -> str | None:
    """장해 지급률 질의에서 핵심 신체 부위·상태 문자열을 추출한다."""

    match = _DISABILITY_RATE_QUESTION_PATTERN.search(question.strip())
    if match:
        phrase = match.group(1).strip()
        phrase = re.sub(r"(인)?\s*경우$", "", phrase).strip()
        if len(phrase) >= 4:
            return phrase

    for keyword in _DISABILITY_KEYWORDS:
        if keyword in question:
            return keyword

    for pattern in (_DISABILITY_QUERY_PATTERN, _DISABILITY_DESC_PATTERN):
        match = pattern.search(question)
        if not match:
            continue
        candidate = match.group(1).strip()
        if len(candidate) >= 2:
            return candidate
    return None


def _build_structured_context(
    question: str,
    chunks: list[Chunk],
    table_store=None,
) -> str | None:
    """수술종수 또는 장해 지급률 질의에 대해 매칭된 구조화 표 행을 반환한다."""

    surgery_name = _extract_surgery_name_from_query(question)
    disability_region = _extract_disability_region_from_query(question)
    compact_question = re.sub(r"\s+", "", question)
    if surgery_name and any(marker in compact_question for marker in _OLD_SURGERY_TABLE_MARKERS):
        surgery_name = None

    if table_store is not None:
        try:
            if table_store.is_available():
                if surgery_name:
                    result = table_store.lookup_surgery_grade(surgery_name)
                    if result:
                        lines = [
                            "[구조화 데이터 — 직접 조회 (C)]",
                            f"수술명: {result['수술명']}",
                            f"1-3종: {result['종_1_3']} | 1-5종: {result['종_1_5']} | 신1-5종: {result['종_신1_5']}",
                            f"출처: 실무가이드 p.{result['source_page_label']}",
                        ]
                        return "\n".join(lines)

                if disability_region:
                    result = table_store.lookup_disability_rate(disability_region)
                    if result:
                        rate = result.get("지급률")
                        if rate:
                            rate_str = f"{rate}%"
                        else:
                            rate_str = f"{result['지급률_범위_최소']}~{result['지급률_범위_최대']}%"
                        lines = [
                            "[구조화 데이터 — 직접 조회 (C)]",
                            f"신체부위: {result['신체부위']}",
                            f"장해 분류: {result['장해분류']}",
                            f"지급률: {rate_str}",
                            f"출처: 실무가이드 p.{result['source_page_label']}",
                        ]
                        return "\n".join(lines)
        except Exception:
            pass

    if not surgery_name and not disability_region:
        return None

    for chunk in chunks:
        raw_table = chunk.metadata.get("table_json", "{}")
        if raw_table in ("", "{}") or raw_table is None:
            continue
        try:
            table_json = json.loads(raw_table) if isinstance(raw_table, str) else raw_table
        except Exception:
            continue
        if not isinstance(table_json, dict):
            continue

        headers = table_json.get("headers")
        rows = table_json.get("rows")
        if not isinstance(headers, list) or not isinstance(rows, list):
            continue

        doc_short = str(chunk.metadata.get("doc_short", "")).strip() or "문서"
        page_start = chunk.metadata.get("page_start", "?")

        if surgery_name and "수술명" in headers:
            query_name_norm = _normalize_surgery_match_text(surgery_name)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                surgery_cell = str(row.get("수술명", "")).strip()
                if not surgery_cell:
                    continue
                surgery_cell_norm = _normalize_surgery_match_text(surgery_cell)
                if not query_name_norm or not surgery_cell_norm:
                    continue
                if query_name_norm in surgery_cell_norm or surgery_cell_norm in query_name_norm:
                    row_parts = [f"수술명: {surgery_cell}"]
                    for col in ("1-3종", "1-5종", "신1-5종"):
                        if col in row:
                            row_parts.append(f"{col}: {row[col]}")
                    row_text = " | ".join(row_parts)
                    return f"[구조화 데이터 — 검색 결과 기반]\n{row_text}\n출처: {doc_short} p.{page_start}"

        if disability_region and "지급률" in headers:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                category = str(row.get("장해의 분류", "")).strip()
                if not category:
                    continue
                if disability_region in category:
                    rate = str(row.get("지급률", "")).strip()
                    if rate and not rate.endswith("%"):
                        rate = f"{rate}%"
                    return (
                        "[구조화 데이터 — 검색 결과 기반]\n"
                        f"장해 분류: {category[:80]}\n"
                        f"지급률: {rate}\n"
                        f"출처: {doc_short} p.{page_start}"
                    )

    return None


def _boost_surgery_name_table_rows(hits: list[Hit], surgery_name: str) -> list[Hit]:
    """수술명이 table_json의 '수술명' 컬럼에 매칭되는 청크를 앞으로 정렬한다."""

    if not hits or not surgery_name:
        return hits

    query_name = surgery_name.strip()
    query_name_norm = _normalize_surgery_match_text(query_name)
    matched: list[Hit] = []
    unmatched: list[Hit] = []

    for hit in hits:
        raw_table = hit.metadata.get("table_json")
        table_json: dict | None = None
        if isinstance(raw_table, str) and raw_table and raw_table != "{}":
            try:
                loaded = json.loads(raw_table)
            except Exception:
                loaded = None
            if isinstance(loaded, dict):
                table_json = loaded
        elif isinstance(raw_table, dict):
            table_json = raw_table

        has_match = False
        if table_json:
            rows = table_json.get("rows", [])
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    cell = str(row.get("수술명", "")).strip()
                    if not cell:
                        continue
                    cell_norm = _normalize_surgery_match_text(cell)
                    if not query_name_norm or not cell_norm:
                        continue
                    if query_name_norm in cell_norm or cell_norm in query_name_norm:
                        has_match = True
                        break

        if has_match:
            matched.append(hit)
        else:
            unmatched.append(hit)

    return matched + unmatched


def _is_low_value_wide_range(hit: Hit) -> bool:
    """광범위한 검색으로 인해 엉뚱한 정보가 잡힌 경우를 식별한다."""
    doc = hit.document
    if ("[별표 7]" in doc and "수술분류표" in doc) or ("[별표 8]" in doc and "수술코드" in doc):
        return True
    start = hit.metadata.get("page_start")
    end = hit.metadata.get("page_end", start)
    if start is None or end is None:
        return False
    char_count = hit.metadata.get("char_count", len(hit.document))
    return (end - start) > 10 and char_count < 300

def _normalize_answer_text(answer: str) -> str:
    """모델 출력의 호환 문자와 HTML 줄바꿈 토큰을 UI/채점 친화적으로 정리한다."""

    return (
        answer.replace("\u2011", "-")
        .replace("\u2010", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2212", "-")
        .replace("\u202f", " ")
        .replace("&lt;br&gt;", "\n")
        .replace("<br>", "\n")
    )


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _split_evidence_lines(text: str) -> list[str]:
    normalized = re.sub(r"[ \t]+", " ", text or "")
    lines = [line.strip(" \t-•*") for line in re.split(r"[\r\n]+", normalized) if line.strip()]
    if len(lines) <= 2:
        lines = [
            sentence.strip(" \t-•*")
            for sentence in re.split(r"(?<=[.。])\s+|(?<=다\.)\s*", normalized)
            if sentence.strip()
        ]
    return lines


def _split_clause_detail_after_pattern(line: str, pattern: re.Pattern[str]) -> list[str]:
    parts = pattern.split(line)
    if len(parts) <= 1:
        return [line]
    if pattern.groups <= 0:
        return [part.strip(" \t-•*") for part in parts if part.strip(" \t-•*")]

    candidates: list[str] = []
    buffer = ""
    for index, part in enumerate(parts):
        if not part:
            continue
        buffer += part
        if index % 2 == 1:
            candidate = buffer.strip(" \t-•*")
            if candidate:
                candidates.append(candidate)
            buffer = ""
    tail = buffer.strip(" \t-•*")
    if tail:
        candidates.append(tail)
    return candidates or [line]


def _extract_clause_detail_numbers(text: str) -> list[str]:
    """근거 문장에 실제로 존재하는 수치 표현만 순서대로 반환한다."""

    numbers: list[str] = []
    number_pattern = _clause_detail_pattern("number_pattern", _CLAUSE_DETAIL_NUMBER_PATTERN)
    for match in number_pattern.finditer(text or ""):
        value = re.sub(r"\s+", "", match.group(0))
        if value not in numbers:
            numbers.append(value)
    return numbers


def _clause_detail_question_facets(question: str) -> list[str]:
    """조항 세부 질문에서 row 매칭에 쓸 일반 facet을 추출한다."""

    compact = _compact_text(question)
    facet_groups = _clause_detail_policy_groups("facet_groups", _CLAUSE_DETAIL_FACET_GROUPS)
    facets: list[str] = []
    for group in facet_groups:
        for term in group:
            if term in compact and term not in facets:
                facets.append(term)
    article_pattern = _clause_detail_pattern("article_pattern", _CLAUSE_DETAIL_ARTICLE_PATTERN)
    for match in article_pattern.findall(question):
        normalized = _compact_text(match)
        if normalized and normalized not in facets:
            facets.append(normalized)
    return facets


def _clause_detail_required_facet_groups(question_facets: list[str]) -> list[tuple[str, ...]]:
    groups: list[tuple[str, ...]] = []
    for group in _clause_detail_policy_groups("required_facet_groups", _CLAUSE_DETAIL_REQUIRED_FACET_GROUPS):
        if any(facet in question_facets for facet in group):
            groups.append(group)
    return groups


def _clause_detail_contains_facet(compact_row: str, facet: str) -> bool:
    if facet == "급여":
        return "급여" in compact_row and "비급여" not in compact_row
    if facet == "비급여":
        return "비급여" in compact_row
    if facet == "3대비급여":
        return "3대비급여" in compact_row or "비급여(3대)" in compact_row
    return facet in compact_row


def _clause_detail_row_matches_required_groups(
    compact_row: str,
    question_facets: list[str],
    groups: list[tuple[str, ...]],
) -> bool:
    for group in groups:
        required = [facet for facet in group if facet in question_facets]
        if required and not any(_clause_detail_contains_facet(compact_row, facet) for facet in required):
            return False
    return True


def _clause_detail_has_coverage_conflict(compact_row: str, question_facets: list[str]) -> bool:
    conflict_rules = _clause_detail_policy().get("coverage_conflicts")
    if isinstance(conflict_rules, list):
        for rule in conflict_rules:
            if not isinstance(rule, dict):
                continue
            question_any = tuple(str(term) for term in rule.get("when_question_has_any", []) if str(term))
            if question_any and not any(term in question_facets for term in question_any):
                continue
            question_unless = tuple(str(term) for term in rule.get("unless_question_has_any", []) if str(term))
            if question_unless and any(term in question_facets for term in question_unless):
                continue
            reject_terms = tuple(str(term) for term in rule.get("reject_row_has", []) if str(term))
            if not reject_terms or not any(_clause_detail_contains_facet(compact_row, term) for term in reject_terms):
                continue
            row_unless = tuple(str(term) for term in rule.get("unless_row_has_any", []) if str(term))
            if row_unless and any(_clause_detail_contains_facet(compact_row, term) for term in row_unless):
                continue
            return True
        return False
    wants_three_nonpay = "3대비급여" in question_facets
    wants_nonpay = wants_three_nonpay or "비급여" in question_facets
    wants_pay = "급여" in question_facets and not wants_nonpay
    row_has_three_nonpay = _clause_detail_contains_facet(compact_row, "3대비급여")
    row_has_nonpay = _clause_detail_contains_facet(compact_row, "비급여")
    row_has_pay = _clause_detail_contains_facet(compact_row, "급여")
    if wants_three_nonpay and row_has_pay and not row_has_three_nonpay:
        return True
    if wants_nonpay and row_has_pay and not row_has_nonpay:
        return True
    if wants_pay and row_has_nonpay:
        return True
    return False


def _split_clause_detail_row_candidates(text: str) -> list[str]:
    """OCR/table-like paragraph를 조항·표 row 후보 단위로 나눈다."""

    normalized = re.sub(r"[ \t]+", " ", text or "")
    row_boundary_pattern = _clause_detail_pattern("row_boundary_pattern", _CLAUSE_DETAIL_ROW_BOUNDARY_PATTERN)
    row_split_after_pattern = _clause_detail_pattern("row_split_after_pattern", _CLAUSE_DETAIL_ROW_SPLIT_AFTER_PATTERN)
    prefix_pattern = _clause_detail_pattern("prefix_pattern", _CLAUSE_DETAIL_PREFIX_PATTERN)
    reset_terms = _clause_detail_policy_terms("context_reset_terms", _CLAUSE_DETAIL_CONTEXT_RESET_TERMS)
    normalized = row_boundary_pattern.sub("\n", normalized)
    candidates: list[str] = []
    context_prefix = ""
    for line in _split_evidence_lines(normalized):
        if len(line) > 340:
            parts = _split_clause_detail_after_pattern(line, row_split_after_pattern)
        else:
            parts = [line]
        for part in parts:
            if not part:
                continue
            compact_part = _compact_text(part)
            is_row_prefix = (
                len(part) <= 80
                and not _extract_clause_detail_numbers(part)
                and bool(prefix_pattern.search(part))
            )
            candidate = f"{context_prefix} {part}".strip() if context_prefix and not is_row_prefix else part
            if candidate and candidate not in candidates:
                candidates.append(candidate)
            if is_row_prefix:
                context_prefix = part
            elif _extract_clause_detail_numbers(part) or any(term in compact_part for term in reset_terms):
                context_prefix = ""
    return candidates


def _score_clause_detail_row(
    row_text: str,
    *,
    question_facets: list[str],
    category_keywords: tuple[str, ...],
) -> int:
    compact_row = _compact_text(row_text)
    score = 0
    for facet in question_facets:
        if facet and _clause_detail_contains_facet(compact_row, facet):
            score += _clause_detail_score_weight("facet")
    for keyword in category_keywords:
        compact_keyword = _compact_text(keyword)
        if compact_keyword and compact_keyword in compact_row:
            score += _clause_detail_score_weight("category_keyword")
    if _extract_clause_detail_numbers(row_text):
        score += _clause_detail_score_weight("number")
    article_pattern = _clause_detail_pattern("article_pattern", _CLAUSE_DETAIL_ARTICLE_PATTERN)
    if article_pattern.search(row_text):
        score += _clause_detail_score_weight("article")
    return score


def _clause_detail_has_category_context(row_text: str, category_keywords: tuple[str, ...]) -> bool:
    compact_row = _compact_text(row_text)
    return any(_compact_text(keyword) in compact_row for keyword in category_keywords)


def _extract_clause_detail_source_label(text: str) -> str:
    labels: list[str] = []
    article_pattern = _clause_detail_pattern("article_pattern", _CLAUSE_DETAIL_ARTICLE_PATTERN)
    for match in article_pattern.findall(text or ""):
        label = re.sub(r"\s+", "", match)
        table_match = re.search(r"표(\d+)", label)
        if table_match:
            label = f"<표{table_match.group(1)}>"
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= 2:
            break
    return " ".join(labels)


def _load_clause_detail_table_json(chunk: Chunk) -> dict[str, Any] | None:
    raw_table = chunk.metadata.get("table_json")
    if raw_table in (None, "", "{}"):
        return None
    if isinstance(raw_table, dict):
        table_json = raw_table
    else:
        try:
            table_json = json.loads(str(raw_table))
        except (TypeError, json.JSONDecodeError):
            return None
    if not isinstance(table_json, dict):
        return None
    headers = table_json.get("headers")
    rows = table_json.get("rows")
    if not isinstance(headers, list) or not isinstance(rows, list) or not rows:
        return None
    return table_json


def _normalize_clause_detail_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clause_detail_row_items(row: Any, headers: list[Any]) -> list[tuple[str, str]]:
    normalized_headers = [_normalize_clause_detail_cell(header) for header in headers]
    if isinstance(row, dict):
        items: list[tuple[str, str]] = []
        for header in normalized_headers:
            if not header:
                continue
            value = _normalize_clause_detail_cell(row.get(header, ""))
            if value:
                items.append((header, value))
        for key, raw_value in row.items():
            header = _normalize_clause_detail_cell(key)
            value = _normalize_clause_detail_cell(raw_value)
            if header and value and (header, value) not in items:
                items.append((header, value))
        return items
    if isinstance(row, list):
        items = []
        for index, raw_value in enumerate(row):
            value = _normalize_clause_detail_cell(raw_value)
            if not value:
                continue
            header = normalized_headers[index] if index < len(normalized_headers) else f"col_{index + 1}"
            items.append((header, value))
        return items
    return []


def _clause_detail_row_label(items: list[tuple[str, str]]) -> str:
    label_header_terms = ("구분", "항목", "분류", "보장", "담보", "종목", "치료", "서류")
    for header, value in items:
        if any(term in header for term in label_header_terms):
            return value[:120]
    for _header, value in items:
        if not _extract_clause_detail_numbers(value):
            return value[:120]
    return items[0][1][:120] if items else ""


def _clause_detail_source_parts(source_label: str) -> tuple[str, str]:
    article_labels: list[str] = []
    table_labels: list[str] = []
    for label in source_label.split():
        if label.startswith("제") and label not in article_labels:
            article_labels.append(label)
        if "표" in label and label not in table_labels:
            table_labels.append(label)
    return " ".join(article_labels), " ".join(table_labels)


def _extract_clause_detail_table_rows(
    question: str,
    chunks: list[Chunk],
    categories: list[str],
    *,
    limit: int = 5,
) -> list[ClauseDetailEvidenceRow]:
    """OCR table_json에서 조항 세부 근거 row를 source-grounded evidence로 변환한다."""

    question_facets = _clause_detail_question_facets(question)
    required_facet_groups = _clause_detail_required_facet_groups(question_facets)
    category_keywords = tuple(
        dict.fromkeys(
            keyword
            for category in categories
            for keyword in _clause_detail_context_terms(category)
        )
    )
    rows: list[ClauseDetailEvidenceRow] = []
    seen: set[tuple[str, str, str]] = set()
    for chunk in chunks:
        table_json = _load_clause_detail_table_json(chunk)
        if table_json is None:
            continue
        headers = table_json.get("headers") or []
        table_rows = table_json.get("rows") or []
        doc_short = str(chunk.metadata.get("doc_short") or "문서")
        page_start = chunk.metadata.get("page_start")
        page_end = chunk.metadata.get("page_end", page_start)
        metadata_section = str(
            chunk.metadata.get("section")
            or chunk.metadata.get("chapter")
            or chunk.metadata.get("part")
            or ""
        )
        parent_heading = metadata_section
        source_label = _extract_clause_detail_source_label(f"{metadata_section} {chunk.text}")
        article, table_label = _clause_detail_source_parts(source_label)
        if source_label and source_label not in metadata_section:
            section = f"{source_label}, {metadata_section}" if metadata_section else source_label
        else:
            section = metadata_section
        for row_index, raw_row in enumerate(table_rows):
            items = _clause_detail_row_items(raw_row, headers)
            if not items:
                continue
            row_label = _clause_detail_row_label(items)
            value_text = " | ".join(f"{header}: {value}" for header, value in items)
            match_text = " ".join(part for part in (source_label, parent_heading, row_label, value_text) if part)
            compact_row = _compact_text(match_text)
            numbers = _extract_clause_detail_numbers(value_text)
            if "deductible" in categories and not numbers:
                continue
            if not _clause_detail_row_matches_required_groups(
                compact_row,
                question_facets,
                required_facet_groups,
            ):
                continue
            if _clause_detail_has_coverage_conflict(compact_row, question_facets):
                continue
            if "deductible" in categories and not _clause_detail_has_category_context(match_text, category_keywords):
                continue
            score = _score_clause_detail_row(
                match_text,
                question_facets=question_facets,
                category_keywords=category_keywords,
            )
            score += _clause_detail_score_weight("table_row")
            if source_label:
                score += _clause_detail_score_weight("source_label")
            if score < _clause_detail_score_weight("min_score"):
                continue
            if question_facets and not any(
                _clause_detail_contains_facet(compact_row, facet) for facet in question_facets
            ):
                continue
            key = (doc_short, str(page_start), _compact_text(value_text)[:220])
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                ClauseDetailEvidenceRow(
                    score=score,
                    text=value_text[:420] + ("..." if len(value_text) > 420 else ""),
                    numbers=numbers,
                    doc_short=doc_short,
                    page_start=page_start,
                    page_end=page_end,
                    chunk_id=chunk.id,
                    section=section,
                    article=article,
                    table_label=table_label,
                    parent_heading=parent_heading,
                    row_label=row_label,
                    value_text=value_text,
                    source_kind="table_json",
                    source_metadata={
                        "source": "table_json",
                        "headers": [_normalize_clause_detail_cell(header) for header in headers],
                        "row_index": row_index,
                        "table_confidence": table_json.get("avg_confidence"),
                        "source_file": chunk.metadata.get("source_file"),
                    },
                )
            )
    rows.sort(key=lambda row: (-row.score, row.doc_short, row.page_start or 0, row.chunk_id))
    return rows[:limit]


def _extract_clause_detail_text_rows(
    question: str,
    chunks: list[Chunk],
    categories: list[str],
    *,
    limit: int = 5,
) -> list[ClauseDetailEvidenceRow]:
    """table_json이 없거나 부족한 경우 쓰는 text 기반 fallback row 추출."""

    question_facets = _clause_detail_question_facets(question)
    required_facet_groups = _clause_detail_required_facet_groups(question_facets)
    category_keywords = tuple(
        dict.fromkeys(
            keyword
            for category in categories
            for keyword in _clause_detail_context_terms(category)
        )
    )
    rows: list[ClauseDetailEvidenceRow] = []
    seen: set[tuple[str, str, str]] = set()
    for chunk in chunks:
        doc_short = str(chunk.metadata.get("doc_short") or "문서")
        page_start = chunk.metadata.get("page_start")
        page_end = chunk.metadata.get("page_end", page_start)
        metadata_section = str(
            chunk.metadata.get("section")
            or chunk.metadata.get("chapter")
            or chunk.metadata.get("part")
            or ""
        )
        source_label = _extract_clause_detail_source_label(chunk.text)
        article, table_label = _clause_detail_source_parts(source_label)
        if source_label and source_label not in metadata_section:
            section = f"{source_label}, {metadata_section}" if metadata_section else source_label
        else:
            section = metadata_section
        for row_text in _split_clause_detail_row_candidates(chunk.text):
            compact_row = _compact_text(row_text)
            numbers = _extract_clause_detail_numbers(row_text)
            if "deductible" in categories and not numbers:
                continue
            if not _clause_detail_row_matches_required_groups(
                compact_row,
                question_facets,
                required_facet_groups,
            ):
                continue
            if _clause_detail_has_coverage_conflict(compact_row, question_facets):
                continue
            if "deductible" in categories and not _clause_detail_has_category_context(row_text, category_keywords):
                continue
            score = _score_clause_detail_row(
                row_text,
                question_facets=question_facets,
                category_keywords=category_keywords,
            )
            if source_label:
                score += _clause_detail_score_weight("source_label")
            if score < _clause_detail_score_weight("min_score"):
                continue
            if question_facets and not any(
                _clause_detail_contains_facet(compact_row, facet) for facet in question_facets
            ):
                continue
            key = (doc_short, str(page_start), _compact_text(row_text)[:220])
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                ClauseDetailEvidenceRow(
                    score=score,
                    text=row_text[:360] + ("..." if len(row_text) > 360 else ""),
                    numbers=numbers,
                    doc_short=doc_short,
                    page_start=page_start,
                    page_end=page_end,
                    chunk_id=chunk.id,
                    section=section,
                    article=article,
                    table_label=table_label,
                    parent_heading=metadata_section,
                    row_label=row_text[:120],
                    value_text=row_text,
                    source_kind="text",
                    source_metadata={
                        "source": "chunk_text",
                        "source_file": chunk.metadata.get("source_file"),
                    },
                )
            )
    rows.sort(key=lambda row: (-row.score, row.doc_short, row.page_start or 0, row.chunk_id))
    return rows[:limit]


def _extract_clause_detail_manifest_rows(
    question: str,
    records: list[ClauseDetailRowRecord] | tuple[ClauseDetailRowRecord, ...],
    categories: list[str],
    *,
    doc_filter: list[str] | None = None,
    limit: int = 5,
) -> list[ClauseDetailEvidenceRow]:
    """Persisted clause_detail_rows manifest에서 질문과 맞는 source row를 찾는다."""

    if not records:
        return []
    allowed_docs = set(doc_filter or [])
    question_facets = _clause_detail_question_facets(question)
    required_facet_groups = _clause_detail_required_facet_groups(question_facets)
    category_keywords = tuple(
        dict.fromkeys(
            keyword
            for category in categories
            for keyword in _clause_detail_context_terms(category)
        )
    )
    rows: list[ClauseDetailEvidenceRow] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        if allowed_docs and record.doc_short not in allowed_docs:
            continue
        match_text = record.search_text
        compact_row = _compact_text(match_text)
        numbers = list(record.numbers)
        if "deductible" in categories and not numbers:
            continue
        if not _clause_detail_row_matches_required_groups(
            compact_row,
            question_facets,
            required_facet_groups,
        ):
            continue
        if _clause_detail_has_coverage_conflict(compact_row, question_facets):
            continue
        if "deductible" in categories and not _clause_detail_has_category_context(match_text, category_keywords):
            continue
        score = _score_clause_detail_row(
            match_text,
            question_facets=question_facets,
            category_keywords=category_keywords,
        )
        score += _clause_detail_score_weight("table_row")
        if record.article or record.table_label:
            score += _clause_detail_score_weight("source_label")
        if score < _clause_detail_score_weight("min_score"):
            continue
        if question_facets and not any(
            _clause_detail_contains_facet(compact_row, facet) for facet in question_facets
        ):
            continue
        key = (record.doc_short, str(record.page), _compact_text(record.value_text)[:220])
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            ClauseDetailEvidenceRow(
                score=score,
                text=record.value_text[:420] + ("..." if len(record.value_text) > 420 else ""),
                numbers=numbers,
                doc_short=record.doc_short,
                page_start=record.page,
                page_end=record.page,
                chunk_id=record.chunk_id,
                section=", ".join(part for part in (record.article, record.table_label, record.parent_heading) if part),
                article=record.article,
                table_label=record.table_label,
                parent_heading=record.parent_heading,
                row_label=record.row_label,
                value_text=record.value_text,
                source_kind="clause_detail_rows",
                source_metadata={
                    **record.source_metadata,
                    "source": "clause_detail_rows",
                    "row_id": record.row_id,
                },
            )
        )
    rows.sort(key=lambda row: (-row.score, row.doc_short, row.page_start or 0, row.chunk_id))
    return rows[:limit]


def _extract_clause_detail_evidence_rows(
    question: str,
    chunks: list[Chunk],
    categories: list[str],
    *,
    manifest_rows: list[ClauseDetailEvidenceRow] | None = None,
    limit: int = 5,
) -> list[ClauseDetailEvidenceRow]:
    """검색된 chunk에서 질문 facet과 숫자를 함께 가진 source-grounded row를 찾는다."""

    table_rows = _extract_clause_detail_table_rows(question, chunks, categories, limit=limit * 2)
    combined = list(manifest_rows or [])
    seen = {
        (row.doc_short, str(row.page_start), _compact_text(row.value_text or row.text)[:220])
        for row in combined
    }
    for row in table_rows:
        key = (row.doc_short, str(row.page_start), _compact_text(row.value_text or row.text)[:220])
        if key in seen:
            continue
        combined.append(row)
        seen.add(key)

    text_rows = _extract_clause_detail_text_rows(question, chunks, categories, limit=limit * 2)
    for row in text_rows:
        key = (row.doc_short, str(row.page_start), _compact_text(row.value_text or row.text)[:220])
        if key in seen:
            continue
        combined.append(row)
        seen.add(key)
    sorted_rows = sorted(
        combined,
        key=lambda row: (
            0 if row.source_kind in {"clause_detail_rows", "table_json"} else 1,
            -row.score,
            row.doc_short,
            row.page_start or 0,
            row.chunk_id,
        ),
    )
    selected: list[ClauseDetailEvidenceRow] = []
    selected_keys: set[tuple[str, str, str]] = set()
    covered_numbers: set[str] = set()
    for row in sorted_rows:
        key = (row.doc_short, str(row.page_start), _compact_text(row.value_text or row.text)[:220])
        row_numbers = {number for number in row.numbers if number}
        if not row_numbers or row_numbers.issubset(covered_numbers):
            continue
        selected.append(row)
        selected_keys.add(key)
        covered_numbers.update(row_numbers)
        if len(selected) >= limit:
            return selected
    for row in sorted_rows:
        key = (row.doc_short, str(row.page_start), _compact_text(row.value_text or row.text)[:220])
        if key in selected_keys:
            continue
        selected.append(row)
        selected_keys.add(key)
        if len(selected) >= limit:
            break
    return selected


def _format_clause_detail_source(row: ClauseDetailEvidenceRow) -> str:
    page = "p.?"
    if row.page_start is not None and row.page_end is not None and row.page_end != row.page_start:
        page = f"p.{row.page_start}-{row.page_end}"
    elif row.page_start is not None:
        page = f"p.{row.page_start}"
    section = f", {row.section}" if row.section else ""
    row_ref = ""
    if row.source_kind == "table_json":
        row_index = row.source_metadata.get("row_index")
        row_ref = f", source=table_json row={row_index}" if row_index is not None else ", source=table_json"
    elif row.source_kind == "clause_detail_rows":
        row_id = row.source_metadata.get("row_id")
        row_ref = f", source=clause_detail_rows row_id={row_id}" if row_id else ", source=clause_detail_rows"
    elif row.source_kind:
        row_ref = f", source={row.source_kind}"
    return f"{row.doc_short}{section}, {page}, chunk={row.chunk_id}{row_ref}"


def _build_clause_detail_evidence_answer(
    question: str,
    rows: list[ClauseDetailEvidenceRow],
    categories: list[str],
) -> str | None:
    if not rows:
        return None

    category_labels = {
        "diagnosis": "진단확정 기준",
        "documents": "청구 필요 서류",
        "deductible": "자기부담금/공제 기준",
        "limit": "보상한도/횟수/기간 기준",
    }
    label = " / ".join(category_labels.get(category, "조항 세부 기준") for category in categories)
    displayed_rows = rows[:2]
    all_numbers: list[str] = []
    for row in displayed_rows:
        for number in row.numbers:
            if number not in all_numbers:
                all_numbers.append(number)

    lines = [
        "제공된 문서 근거에서 확인되는 범위로 답변드립니다.",
        "",
        f"{label}: 아래 원문 근거 행을 우선 확인했습니다.",
    ]
    for index, row in enumerate(displayed_rows, start=1):
        lines.append(f"- 근거 {index}: {row.text}")
        if row.numbers:
            lines.append(f"  - 확인된 수치: {', '.join(row.numbers)}")
        lines.append(f"  - 출처: {_format_clause_detail_source(row)}")
    if all_numbers:
        lines.extend(["", f"확인된 수치 요약: {', '.join(all_numbers)}"])
    lines.extend(
        [
            "",
            "위 내용은 선택된 원문 근거 기준의 구조화 요약입니다. 실제 지급 여부는 가입 담보와 사고/진단 사실 관계를 함께 확인해야 합니다.",
        ]
    )
    return "\n".join(lines)


def _extract_clause_evidence_lines(text: str, keywords: tuple[str, ...], limit: int = 6) -> list[str]:
    compact_keywords = tuple(_compact_text(keyword) for keyword in keywords if keyword)
    selected: list[str] = []
    seen: set[str] = set()
    for line in _split_evidence_lines(text):
        compact_line = _compact_text(line)
        if not compact_line or not any(keyword in compact_line for keyword in compact_keywords):
            continue
        line = line[:260] + ("..." if len(line) > 260 else "")
        key = _compact_text(line)
        if key in seen:
            continue
        seen.add(key)
        selected.append(line)
        if len(selected) >= limit:
            break
    return selected


def _deterministic_clause_detail_answer(
    question: str,
    chunks: list[Chunk],
    manifest_rows: list[ClauseDetailEvidenceRow] | None = None,
) -> str | None:
    """조항 세부 근거가 검색된 경우 LLM의 '컨텍스트 없음' 오판을 방지한다."""

    categories = _clause_detail_categories(question)
    if not categories:
        return None

    source_rows = _extract_clause_detail_evidence_rows(
        question,
        chunks,
        categories,
        manifest_rows=manifest_rows,
    )
    source_grounded_answer = _build_clause_detail_evidence_answer(question, source_rows, categories)
    if source_grounded_answer:
        return source_grounded_answer

    category_labels = {
        "diagnosis": "진단확정 기준",
        "documents": "청구 필요 서류",
        "deductible": "자기부담금 기준",
        "limit": "보상한도/횟수/기간 기준",
    }
    evidence_lines: list[str] = []
    seen_evidence_line_keys: set[str] = set()
    for category in categories:
        keywords = _clause_detail_context_terms(category)
        category_hits: list[tuple[int, Chunk, list[str]]] = []
        for chunk in chunks:
            lines = _extract_clause_evidence_lines(chunk.text, keywords)
            if not lines:
                continue
            score = sum(1 for keyword in keywords if _compact_text(keyword) in _compact_text(chunk.text))
            category_hits.append((score, chunk, lines))
        if not category_hits:
            continue
        category_hits.sort(key=lambda item: item[0], reverse=True)
        evidence_lines.append(f"{category_labels.get(category, '조항 세부 기준')}: 검색된 약관 근거에서 다음과 같이 확인됩니다.")
        for _score, _chunk, lines in category_hits[:2]:
            for line in lines[:4]:
                line_key = _compact_text(line)
                if line_key in seen_evidence_line_keys:
                    continue
                seen_evidence_line_keys.add(line_key)
                evidence_lines.append(f"- {line}")

    if not evidence_lines:
        return None

    return "\n".join(
        [
            "제공된 문서 근거에서 확인되는 범위로 답변드립니다.",
            "",
            *evidence_lines,
            "",
            "위 내용은 검색된 조항 문구 기준의 요약이며, 실제 지급 여부는 가입 담보와 사고/진단 사실 관계를 함께 확인해야 합니다.",
        ]
    )


def _deterministic_guard_answer(
    question: str,
    chunks: list[Chunk],
    graph_context: str | None = None,
    clause_detail_rows: list[ClauseDetailEvidenceRow] | None = None,
    graph_result: Any | None = None,
    table_store: TableStore | None = None,
) -> str | None:
    procedure_grade = resolve_procedure_grade(
        question,
        table_store=table_store,
        graph_result=graph_result,
    )
    if procedure_grade is not None:
        return format_procedure_grade_answer(procedure_grade)

    absent_code_answer = build_absent_code_guard_answer(question, chunks)
    if absent_code_answer:
        return absent_code_answer

    clause_detail_answer = _deterministic_clause_detail_answer(
        question,
        chunks,
        manifest_rows=clause_detail_rows,
    )
    if clause_detail_answer:
        return clause_detail_answer

    comparison_answer = build_generation_deductible_comparison_answer(question)
    if comparison_answer:
        return comparison_answer

    hira_ctx = _build_hira_fee_context(question, graph_context=graph_context)
    hira_answer = build_hira_fee_answer(question, hira_ctx)
    if hira_answer:
        return hira_answer
    return None


def _exclude_irrelevant_travel_insurance(hits: list[Hit], question: str) -> list[Hit]:
    """질문에 '해외'나 '여행', '유학'이 없는 경우, 해외여행자보험 관련 청크를 필터링한다."""
    if any(keyword in question for keyword in ["해외", "여행", "유학"]):
        return hits

    filtered = []
    for hit in hits:
        doc_text = hit.document.replace(" ", "")
        if "해외여행" in doc_text and "실손의료보험" in doc_text:
            continue
        if "해외체류" in hit.document and "해외여행" in hit.document:
            continue
        filtered.append(hit)
    return filtered


def _expand_retrieval_query(question: str) -> str:
    """검색 성능 향상을 위해 질의를 확장한다."""
    return get_default_ontology_registry().expand_retrieval_query(question)


def _clause_detail_categories(question: str) -> list[str]:
    compact = re.sub(r"\s+", "", question)
    categories: list[str] = []
    if any(term in compact for term in ("진단확정", "확정기준", "진단기준")):
        categories.append("diagnosis")
    if any(term in compact for term in ("필요서류", "필요한서류", "청구서류", "제출서류", "구비서류")):
        categories.append("documents")
    if any(term in compact for term in ("자기부담금", "자기부담")):
        categories.append("deductible")
    if any(
        term in compact
        for term in ("보상한도", "보장한도", "지급한도", "연간한도", "횟수한도", "보장기간", "지급기간")
    ):
        categories.append("limit")
    return categories


def _is_clause_detail_query(question: str) -> bool:
    compact = re.sub(r"\s+", "", question)
    return any(term in compact for term in _CLAUSE_DETAIL_QUERY_CUES)


def _expand_clause_detail_query(question: str, retrieval_query: str) -> str:
    """조항 세부 질의에서 일반 표현과 약관 section 표현을 함께 검색한다."""

    terms: list[str] = []
    for category in _clause_detail_categories(question):
        terms.extend(_clause_detail_context_terms(category))
    if not terms:
        return retrieval_query
    suffix = " ".join(term for term in dict.fromkeys(terms) if term not in retrieval_query)
    return f"{retrieval_query} {suffix}".strip()


def _is_low_value_wide_range_filter(hit: Hit) -> bool:
    """목차처럼 넓은 페이지 범위에 짧게 걸친 청크를 검색 후보에서 제외한다."""

    start = hit.metadata.get("page_start")
    end = hit.metadata.get("page_end", start)
    if start is None or end is None:
        return False
    char_count = hit.metadata.get("char_count", len(hit.document))
    return (end - start) > 10 and char_count < 300


def _prefer_exact_text_hits(hits: list[Hit], terms: list[str]) -> list[Hit]:
    """핵심 명칭이 원문에 직접 포함된 검색 결과를 앞쪽으로 정렬한다."""

    if not terms:
        return hits
    compact_terms = [re.sub(r"\s+", "", term) for term in terms if term]

    def exact_score(hit: Hit) -> int:
        compact_document = re.sub(r"\s+", "", hit.document or "")
        return max(
            (len(term) for term in compact_terms if term and term in compact_document),
            default=0,
        )

    return sorted(hits, key=exact_score, reverse=True)


def _filter_hits_by_doc(hits: list[Hit], doc_filter: list[str] | None) -> list[Hit]:
    """선택된 문서 축약명에 해당하는 Hit만 남긴다."""

    if not doc_filter:
        return hits
    allowed = set(doc_filter)
    return [hit for hit in hits if hit.metadata.get("doc_short") in allowed]


def _filter_hits_by_policy_generation(hits: list[Hit], policy_generation: str | None) -> list[Hit]:
    """Keep selected-generation policy hits while retaining generation-neutral evidence."""

    if policy_generation not in {"4th", "5th"}:
        return hits
    return [
        hit
        for hit in hits
        if not hit.metadata.get("policy_generation")
        or str(hit.metadata.get("policy_generation")) == policy_generation
    ]


def _filter_generation_scoped_clause_detail_hits(
    hits: list[Hit],
    question: str,
    policy_generation: str | None,
) -> list[Hit]:
    """Fail closed for direct clause attributes without verified selected-generation evidence."""

    if policy_generation not in {"4th", "5th"} or not _clause_detail_categories(question):
        return hits
    return [
        hit
        for hit in hits
        if str((hit.metadata or {}).get("policy_generation") or "") == policy_generation
    ]


def _hit_dedupe_key(hit: Hit) -> tuple[str, str, str, str, str]:
    """같은 문서/페이지/본문이 다른 chunk id로 반복되는 것을 제거하기 위한 키."""

    metadata = hit.metadata or {}
    doc_key = str(metadata.get("doc_short") or metadata.get("pdf_filename") or metadata.get("source") or "")
    page_start = str(metadata.get("page_start") or "")
    page_end = str(metadata.get("page_end") or page_start or "")
    section = str(metadata.get("section") or metadata.get("section_path") or "")
    text_key = re.sub(r"\s+", "", hit.document or "")[:260]
    return doc_key, page_start, page_end, section, text_key


def _ordered_unique(values: list[str]) -> list[str]:
    """순서를 보존하며 중복을 제거한다."""

    return list(dict.fromkeys(value for value in values if value))


def _infer_requested_doc_shorts(question: str, doc_filter: list[str] | None = None) -> list[str]:
    """질문과 명시 필터에서 문서별 비교에 필요한 문서 축약명을 추론한다."""

    if doc_filter:
        return _ordered_unique(doc_filter)

    compact_question = re.sub(r"\s+", "", question)
    matched: list[str] = []
    for source in config.PDF_SOURCES:
        aliases = [source.doc_short, source.doc_name, source.product_name or ""]
        aliases.extend(_DOC_ALIASES.get(source.doc_short, ()))
        for alias in aliases:
            compact_alias = re.sub(r"\s+", "", str(alias))
            if compact_alias and compact_alias in compact_question:
                matched.append(source.doc_short)
                break
    matched = _ordered_unique(matched)
    if "약관" in matched and any(doc.startswith("자사_") or doc == "표준약관" for doc in matched):
        explicit_policy_aliases = ("실손의료보험약관", "이지로운실손", "질병급여", "질병비급여", "3대비급여")
        if not any(alias in compact_question for alias in explicit_policy_aliases):
            matched = [doc for doc in matched if doc != "약관"]
    return matched


def _needs_doc_coverage(question: str, requested_docs: list[str]) -> bool:
    """문서별 비교/복수 문서 질의라면 검색 결과에 문서 커버리지를 강제한다."""

    if len(requested_docs) < 2:
        return False
    compact_question = re.sub(r"\s+", "", question)
    return any(term in compact_question for term in _DOC_COMPARE_TERMS) or len(requested_docs) >= 2


def _merge_hits_preserving_order(primary: list[Hit], extras: list[Hit], limit: int | None = None) -> list[Hit]:
    """기존 순서를 보존하면서 추가 hit를 중복 없이 병합한다."""

    merged: list[Hit] = []
    seen: set[str] = set()
    seen_content: set[tuple[str, str, str, str, str]] = set()
    for hit in primary + extras:
        content_key = _hit_dedupe_key(hit)
        if hit.id in seen or content_key in seen_content:
            continue
        seen.add(hit.id)
        seen_content.add(content_key)
        merged.append(hit)
        if limit is not None and len(merged) >= limit:
            break
    return merged


def _question_anchor_terms(question: str) -> list[str]:
    """조항 표제어보다 사용자가 실제로 묻는 담보/항목 명칭을 뽑는다."""

    stop_terms = {
        "특별약관",
        "특약",
        "담보",
        "기준",
        "설명",
        "알려줘",
        "알려",
        "청구",
        "필요",
        "필요한",
        "서류",
        "자기부담금",
        "자기부담",
        "진단확정",
        "최초",
        "회한",
    }
    terms: list[str] = []
    for token in re.findall(r"[가-힣A-Za-z0-9]{3,}", question):
        compact_token = _compact_text(token)
        if not compact_token or compact_token in stop_terms:
            continue
        if any(stop in compact_token for stop in ("알려", "설명", "필요", "서류")):
            continue
        if compact_token not in terms:
            terms.append(compact_token)
    return terms[:6]


def _focus_docs_from_clause_hits(question: str, hits: list[Hit], limit: int = 4) -> list[str]:
    """조항성 질의에서 이미 검색된 상품 문서 안으로 보강 검색할 문서를 고른다."""

    scores: dict[str, float] = {}
    anchor_terms = _question_anchor_terms(question)
    for rank, hit in enumerate(hits[:16]):
        doc_short = str((hit.metadata or {}).get("doc_short") or "")
        if not doc_short:
            continue
        if doc_short in {"실무가이드", "심평원"}:
            continue
        score = 1.0 / (rank + 1)
        if doc_short.startswith("자사_"):
            score += 0.35
        compact_doc = _compact_text(hit.document)
        score += sum(0.6 for term in anchor_terms if term in compact_doc)
        scores[doc_short] = scores.get(doc_short, 0.0) + score
    ordered = sorted(scores, key=lambda key: scores[key], reverse=True)
    return ordered[:limit]


def _score_clause_detail_hit(hit: Hit, question: str) -> int:
    compact_doc = re.sub(r"\s+", "", hit.document or "")
    score = 0
    for term in _question_anchor_terms(question):
        if term in compact_doc:
            score += 3
    for category in _clause_detail_categories(question):
        for term in _clause_detail_context_terms(category):
            if re.sub(r"\s+", "", term) in compact_doc:
                score += 2
    if "특별약관" in compact_doc or "담보" in compact_doc:
        score += 1
    return score


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
        table_store: TableStore | None = None,
        clause_detail_row_store: ClauseDetailRowStore | None = None,
        pair_mapping_store=None,
        v1_chunk_lookup: dict[str, dict] | None = None,
        source_chunk_lookup: dict[str, dict] | None = None,
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
        self._table_store = table_store if table_store is not None else TableStore()
        self._clause_detail_row_store = clause_detail_row_store
        self._pair_mapping_store = pair_mapping_store
        self._v1_chunk_lookup = v1_chunk_lookup or {}
        self._source_chunk_lookup = source_chunk_lookup or {}
        if config.resolve_safe_baseline_runtime_root() is not None:
            # Safe-baseline mode must not degrade to a raw or damaged graph path.
            get_default_ontology_registry()
        self.graph_enabled = config.GRAPH_ENABLED and _GRAPH_IMPORT_OK
        if self.graph_enabled:
            try:
                self.graph_retriever = GraphRetriever(config.resolve_graph_index_path())
            except Exception:
                self.graph_retriever = None
                self.graph_enabled = False
        else:
            self.graph_retriever = None

    def _hydrate_source_metadata(self, hits: list[Hit]) -> list[Hit]:
        """Restore missing index metadata from the canonical processed chunk record."""

        if not self._source_chunk_lookup:
            return hits

        fields = (
            "policy_generation",
            "is_own_company",
            "doc_name",
            "product_name",
            "product_type",
            "effective_date",
        )
        for hit in hits:
            source_row = self._source_chunk_lookup.get(hit.id)
            if source_row is None:
                for candidate_id in graph_chunk_fallback_ids(hit.id):
                    source_row = self._source_chunk_lookup.get(candidate_id)
                    if source_row is not None:
                        break
            if not isinstance(source_row, dict):
                continue
            source_metadata = source_row.get("metadata")
            if not isinstance(source_metadata, dict):
                continue
            metadata = dict(hit.metadata or {})
            changed = False
            for field in fields:
                if metadata.get(field) is None and source_metadata.get(field) is not None:
                    metadata[field] = source_metadata[field]
                    changed = True
            if changed:
                hit.metadata = metadata
        return hits

    def _clause_detail_manifest_rows(
        self,
        question: str,
        categories: list[str],
        doc_filter: list[str] | None,
    ) -> list[ClauseDetailEvidenceRow]:
        if self._clause_detail_row_store is None or not self._clause_detail_row_store.is_available():
            return []
        return _extract_clause_detail_manifest_rows(
            question,
            self._clause_detail_row_store.records(),
            categories,
            doc_filter=doc_filter,
        )

    def _build_paired_ocr_context(self, chunks: list[Chunk], max_pairs: int = 3) -> str | None:
        """v2 canonical 청크에 대응하는 v1 원문을 보조 컨텍스트로 구성한다."""

        if self._pair_mapping_store is None or not self._v1_chunk_lookup:
            return None

        lines: list[str] = []
        count = 0
        for chunk in chunks:
            pair = self._pair_mapping_store.get(chunk.id)
            if not pair or not pair.get("use_v1"):
                continue
            v1_chunk_id = pair.get("v1_chunk_id")
            if not v1_chunk_id:
                continue
            v1_row = self._v1_chunk_lookup.get(v1_chunk_id)
            if not v1_row:
                continue
            v1_text = str(v1_row.get("text", "")).strip()
            if not v1_text:
                continue
            preview = v1_text[:500] + ("..." if len(v1_text) > 500 else "")
            lines.append(
                f"[원본OCR 대응 {count+1}] v2={chunk.id} | v1={v1_chunk_id} | score={pair.get('score')}\n{preview}"
            )
            count += 1
            if count >= max_pairs:
                break

        if not lines:
            return None
        return "[OCR 교차검증 컨텍스트 - 원본 OCR 참조]\n" + "\n\n".join(lines)

    def _best_doc_coverage_hits(
        self,
        retrieval_query: str,
        query_embedding,
        requested_docs: list[str],
    ) -> list[Hit]:
        """요청된 각 문서에서 최소 1개 후보를 확보한다."""

        coverage_hits: list[Hit] = []
        for doc_short in requested_docs:
            dense = self.vector_store.query(query_embedding, 1, doc_filter=[doc_short])
            bm25 = _filter_hits_by_doc(self.bm25.query(retrieval_query, 3), [doc_short])[:1]
            best = rrf_fuse(dense, bm25, top_k=1, rrf_k=self.rrf_k)
            coverage_hits.extend(best)
        return coverage_hits

    def _restore_doc_coverage(self, hits: list[Hit], coverage_hits: list[Hit], top_k: int) -> list[Hit]:
        """최종 후보에서 누락된 요청 문서가 있으면 낮은 순위 후보를 교체한다."""

        if not coverage_hits:
            return hits[:top_k]

        selected = _merge_hits_preserving_order(hits, [], limit=top_k)
        present_docs = {hit.metadata.get("doc_short") for hit in selected}
        replacements = [hit for hit in coverage_hits if hit.metadata.get("doc_short") not in present_docs]
        if not replacements:
            return selected

        for replacement in replacements:
            if replacement.id in {hit.id for hit in selected}:
                continue
            if len(selected) < top_k:
                selected.append(replacement)
            else:
                selected[-1] = replacement
            present_docs.add(replacement.metadata.get("doc_short"))
        return _merge_hits_preserving_order(selected, [], limit=top_k)

    def build_prompt(self, question: str, chunks: list[Chunk], graph_context: str | None = None) -> str:
        """일반/스트리밍 경로가 공유하는 근거 보강 프롬프트를 만든다."""

        prompt = build_user_prompt(question, chunks)
        paired_ocr_ctx = self._build_paired_ocr_context(chunks)
        if paired_ocr_ctx:
            prompt = f"{paired_ocr_ctx}\n\n{prompt}"
        structured_ctx = _build_structured_context(question, chunks, table_store=self._table_store)
        if structured_ctx:
            prompt = f"{structured_ctx}\n\n{prompt}"
        hira_fee_ctx = _build_hira_fee_context(question, graph_context=graph_context)
        if hira_fee_ctx:
            prompt = f"{hira_fee_ctx}\n\n{prompt}"
        evidence_ctx = build_strict_evidence_context(question, chunks)
        if evidence_ctx:
            prompt = f"{evidence_ctx}\n\n{prompt}"

        if graph_context:
            prompt = f"{graph_context}\n\n{prompt}"

        # Conflict Detection 적용
        conflict_info = detect_retrieval_conflicts(chunks, question)
        if conflict_info["conflict_detected"]:
            conflict_guideline = (
                "[⚠️ 문서 간 정보 충돌 감지 및 분리 지침]\n"
                f"현재 참조 문서들({', '.join(conflict_info['conflicting_docs'])}) 간에 보상 한도, 횟수, 수치 또는 보상 여부에 차이가 존재합니다.\n"
                "각 문서의 기준을 하나로 뭉뚱그려(평균내어) 설명하지 말고, 반드시 아래와 같이 문서별로 명확히 분리하여 설명하십시오.\n"
                "예시: '[약관] 기준: ... | [자사_SOL건강] 기준: ...'\n"
            )
            prompt = f"{conflict_guideline}\n{prompt}"

        return prompt

    def retrieve_hits(
        self,
        question: str,
        top_k: int | None = None,
        doc_filter: list[str] | None = None,
        return_debug: bool = False,
        graph_hits: list[Hit] | None = None,
        policy_generation: str | None = None,
    ) -> tuple[list[Hit], DebugInfo | None]:
        """질문에 대한 최종 검색 후보를 반환한다."""

        final_top_k = top_k or self.top_k_final
        graph_hits = self._hydrate_source_metadata(list(graph_hits or []))
        search_intent = classify_search_intent(
            question,
            doc_filter=doc_filter,
            default_top_k_dense=self.top_k_dense,
            default_top_k_bm25=self.top_k_bm25,
        )
        retrieval_query = _expand_retrieval_query(question)
        query_codes = _extract_query_codes(question)
        lexical_priority_terms = get_default_ontology_registry().lexical_priority_terms(question)
        named_code_terms = _ordered_unique(_extract_named_code_terms(question) + lexical_priority_terms)
        surgery_name = _extract_surgery_name_from_query(question)
        requested_docs = _infer_requested_doc_shorts(question, doc_filter)
        enforce_doc_coverage = _needs_doc_coverage(question, requested_docs)
        code_hits: list[Hit] = []
        coverage_hits: list[Hit] = []
        dense_hits: list[Hit] = []
        bm25_hits: list[Hit] = []
        query_embedding = None

        dynamic_enabled = config.DYNAMIC_RRF_ENABLED
        dynamic_mode = config.DYNAMIC_RRF_MODE if config.DYNAMIC_RRF_MODE in {"observe", "weighted", "optimized"} else "observe"
        if not dynamic_enabled:
            dynamic_mode = "observe"

        if dynamic_enabled and dynamic_mode in {"weighted", "optimized"}:
            applied_dense_weight = search_intent.dense_weight
            applied_bm25_weight = search_intent.bm25_weight
            dense_top_k = max(1, search_intent.top_k_dense)
            bm25_top_k = max(1, search_intent.top_k_bm25)
            fallback_reason = ""
        else:
            applied_dense_weight = 1.0
            applied_bm25_weight = 1.0
            dense_top_k = max(1, self.top_k_dense)
            bm25_top_k = max(1, self.top_k_bm25)
            fallback_reason = "dynamic RRF observe/disabled: fixed baseline retrieval applied"

        can_skip_general_dense_candidate = (
            dynamic_enabled
            and dynamic_mode == "optimized"
            and config.DYNAMIC_RRF_SKIP_GENERAL_DENSE
            and search_intent.skip_general_dense
            and query_codes
            and not enforce_doc_coverage
            and not search_intent.requires_coverage_judgment
            and not search_intent.requires_clause_lookup
            and not search_intent.requires_cross_document
        )

        should_run_filtered_dense = bool(query_codes and hasattr(self.vector_store, "query_with_filter"))
        should_run_general_dense = True

        if should_run_filtered_dense or should_run_general_dense or enforce_doc_coverage:
            query_embedding = self.embedder.embed_query(retrieval_query)

        if should_run_filtered_dense and query_embedding is not None:
            half_k = max(1, dense_top_k // 2)
            code_hits = self.vector_store.query_with_filter(
                query_embedding,
                filter_codes=query_codes,
                top_k=half_k,
                prefer_non_table=True,
                doc_filter=doc_filter,
            )
            code_hits = self._hydrate_source_metadata(code_hits)
            code_hits = _filter_hits_by_policy_generation(code_hits, policy_generation)

        should_run_general_dense = not (can_skip_general_dense_candidate and bool(code_hits))
        if should_run_general_dense and query_embedding is not None:
            if query_codes and code_hits:
                general_top_k = max(1, dense_top_k // 2)
            else:
                general_top_k = dense_top_k
            general_hits = self.vector_store.query(query_embedding, general_top_k, doc_filter=doc_filter)
            general_hits = self._hydrate_source_metadata(general_hits)
            general_hits = _filter_hits_by_policy_generation(general_hits, policy_generation)
            seen = {hit.id for hit in code_hits}
            dense_hits = code_hits + [hit for hit in general_hits if hit.id not in seen]
        else:
            dense_hits = list(code_hits)

        if not search_intent.skip_bm25:
            bm25_hits = self.bm25.query(retrieval_query, bm25_top_k)
            bm25_hits = self._hydrate_source_metadata(bm25_hits)
            bm25_hits = _filter_hits_by_doc(bm25_hits, doc_filter)
            bm25_hits = _filter_hits_by_policy_generation(bm25_hits, policy_generation)
        execution_info = RetrievalExecutionInfo(
            dynamic_rrf_enabled=dynamic_enabled,
            dynamic_rrf_mode=dynamic_mode,
            applied_dense_weight=applied_dense_weight,
            applied_bm25_weight=applied_bm25_weight,
            applied_top_k_dense=dense_top_k,
            applied_top_k_bm25=bm25_top_k,
            dense_filtered_executed=bool(should_run_filtered_dense and query_embedding is not None),
            dense_general_executed=bool(should_run_general_dense and query_embedding is not None),
            bm25_executed=not search_intent.skip_bm25,
            skipped_general_dense=bool(not should_run_general_dense),
            fallback_reason=fallback_reason,
        )
        debug_dense = list(dense_hits)
        debug_bm25 = list(bm25_hits)
        dense_hits = [hit for hit in dense_hits if not _is_low_value_wide_range(hit)]
        bm25_hits = [hit for hit in bm25_hits if not _is_low_value_wide_range(hit)]

        dense_hits = _exclude_irrelevant_travel_insurance(dense_hits, question)
        bm25_hits = _exclude_irrelevant_travel_insurance(bm25_hits, question)
        clause_detail_hits: list[Hit] = []
        if _is_clause_detail_query(question):
            focus_docs = _ordered_unique(doc_filter or _focus_docs_from_clause_hits(question, dense_hits + bm25_hits))
            if focus_docs:
                detail_query = _expand_clause_detail_query(question, retrieval_query)
                detail_pool_size = max(bm25_top_k * 4, 80)
                detail_candidates = _filter_hits_by_doc(self.bm25.query(detail_query, detail_pool_size), focus_docs)
                detail_candidates = self._hydrate_source_metadata(detail_candidates)
                detail_candidates = _filter_hits_by_policy_generation(detail_candidates, policy_generation)
                scored_detail_hits = [
                    (_score_clause_detail_hit(hit, question), hit)
                    for hit in detail_candidates
                ]
                clause_detail_hits = [
                    hit
                    for score, hit in sorted(scored_detail_hits, key=lambda item: item[0], reverse=True)
                    if score >= 2
                ][: max(4, final_top_k // 2)]

        reranker_enabled = self.reranker is not None and getattr(self.reranker, "enabled", True)
        rrf_top_k = final_top_k * 2 if reranker_enabled else final_top_k
        if surgery_name:
            # 수술명 질의는 인접 페이지 표가 섞이기 쉬워 부스팅 전에 후보 풀을 확장한다.
            rrf_top_k = max(rrf_top_k, final_top_k * 3)
        fused_hits = rrf_fuse(
            dense_hits,
            bm25_hits,
            top_k=rrf_top_k,
            rrf_k=self.rrf_k,
            dense_weight=applied_dense_weight,
            bm25_weight=applied_bm25_weight,
        )
        debug_rrf = list(fused_hits)
        if enforce_doc_coverage and query_embedding is not None:
            coverage_hits = self._best_doc_coverage_hits(retrieval_query, query_embedding, requested_docs)
            fused_hits = _merge_hits_preserving_order(fused_hits, coverage_hits, limit=max(rrf_top_k, final_top_k))
        if code_hits:
            fused_by_id = {hit.id: hit for hit in fused_hits}
            ordered: list[Hit] = []
            seen: set[str] = set()
            for hit in code_hits:
                ordered.append(fused_by_id.get(hit.id, hit))
                seen.add(hit.id)
            ordered.extend(hit for hit in fused_hits if hit.id not in seen)
            fused_hits = ordered[:rrf_top_k]
        else:
            fused_hits = _prefer_exact_text_hits(fused_hits, named_code_terms)

        if surgery_name:
            fused_hits = _boost_surgery_name_table_rows(fused_hits, surgery_name)

        if graph_hits:
            fused_hits = _merge_hits_preserving_order(
                fused_hits,
                _filter_hits_by_policy_generation(graph_hits, policy_generation),
            )
        if clause_detail_hits:
            fused_hits = _merge_hits_preserving_order(
                clause_detail_hits,
                fused_hits,
                limit=max(rrf_top_k, final_top_k),
            )

        reranker_results: list[RerankResult] = []
        if self.reranker is not None:
            if hasattr(self.reranker, "rerank_with_scores"):
                reranker_results = self.reranker.rerank_with_scores(question, fused_hits, top_k=final_top_k)
                final_hits = [result.hit for result in reranker_results]
            else:
                final_hits = self.reranker.rerank(question, fused_hits, top_k=final_top_k)
                reranker_results = [
                    RerankResult(hit=hit, score=float(hit.score), rank=index + 1)
                    for index, hit in enumerate(final_hits)
                ]
        else:
            final_hits = fused_hits[:final_top_k]

        if clause_detail_hits:
            final_hits = _merge_hits_preserving_order(clause_detail_hits, final_hits, limit=final_top_k)
        if graph_hits:
            final_hits = _merge_hits_preserving_order(
                final_hits,
                _filter_hits_by_policy_generation(graph_hits, policy_generation),
                limit=final_top_k,
            )
        if enforce_doc_coverage:
            final_hits = self._restore_doc_coverage(final_hits, coverage_hits, final_top_k)
        final_hits = self._hydrate_source_metadata(final_hits)
        final_hits = _filter_hits_by_policy_generation(final_hits, policy_generation)
        final_hits = _filter_generation_scoped_clause_detail_hits(
            final_hits,
            question,
            policy_generation,
        )
        final_hits = _prefer_exact_text_hits(final_hits, named_code_terms)
        debug = (
            DebugInfo(
                dense_hits=_hits_to_stage(debug_dense),
                bm25_hits=_hits_to_stage(debug_bm25),
                rrf_hits=_hits_to_stage(debug_rrf),
                final_hits=_hits_to_stage(final_hits),
                search_intent=search_intent,
                retrieval_execution=execution_info,
                reranker_scores=_rerank_results_to_stage(reranker_results),
            )
            if return_debug
            else None
        )
        return final_hits, debug

    def answer(
        self,
        question: str,
        temperature: float = 0.2,
        top_k: int | None = None,
        doc_filter: list[str] | None = None,
        return_debug: bool = False,
        auto_params: AutoRagParams | None = None,
        policy_generation: str | None = None,
    ) -> RagAnswer:
        """질문에 대해 답변과 사용한 청크를 반환한다."""

        total_started = time.perf_counter()
        retrieve_started = time.perf_counter()

        graph_result = None
        graph_context = ""
        graph_hits = []
        if self.graph_enabled and self.graph_retriever:
            try:
                graph_result = self.graph_retriever.retrieve(question)
                graph_context = build_graph_context(graph_result)
                if graph_result.source_chunk_refs:
                    graph_hits = self.vector_store.get_by_refs(graph_result.source_chunk_refs)
                elif graph_result.source_chunk_ids:
                    graph_hits = self.vector_store.get_by_ids(graph_result.source_chunk_ids)
                if graph_result.source_chunk_ids:
                    retrieved_ids = {hit.id for hit in graph_hits}
                    missing_ids = [cid for cid in graph_result.source_chunk_ids if cid not in retrieved_ids]
                    if missing_ids:
                        seen_hit_ids = {hit.id for hit in graph_hits}
                        for fact in graph_result.facts:
                            for evidence in fact.evidence:
                                if evidence.chunk_id not in missing_ids:
                                    continue
                                if not hasattr(self.vector_store, "get_by_doc_page"):
                                    continue
                                for hit in self.vector_store.get_by_doc_page(
                                    evidence.doc_short,
                                    evidence.page_start,
                                    evidence.page_end,
                                    limit=3,
                                ):
                                    if hit.id not in seen_hit_ids:
                                        graph_hits.append(hit)
                                        seen_hit_ids.add(hit.id)
                        retrieved_ids.update(hit.id for hit in graph_hits)
                        missing_ids = [
                            cid
                            for cid in graph_result.source_chunk_ids
                            if cid not in retrieved_ids
                            and not any(
                                evidence.chunk_id == cid
                                and evidence.doc_short
                                and evidence.page_start is not None
                                for fact in graph_result.facts
                                for evidence in fact.evidence
                            )
                        ]
                    if missing_ids:
                        import logging
                        logging.warning(f"Graph source chunks {missing_ids} not found in Chroma vector store. Ignored.")
            except Exception as e:
                import logging
                logging.warning(f"Graph retrieval failed, falling back to standard RAG: {e}")
                graph_result = None
                graph_context = ""
                graph_hits = []


        fused_hits, debug = self.retrieve_hits(
            question,
            top_k=top_k,
            doc_filter=doc_filter,
            return_debug=return_debug,
            graph_hits=graph_hits,
            policy_generation=policy_generation,
        )
        if auto_params is not None:
            preserve_ids = {hit.id for hit in graph_hits}
            fused_hits, cutoff = apply_adaptive_k_to_hits(
                fused_hits,
                list(getattr(debug, "reranker_scores", []) or []),
                auto_params,
                score_floor=config.AUTO_RAG_RERANK_SCORE_FLOOR,
                drop_abs=config.AUTO_RAG_RERANK_DROP_ABS,
                drop_ratio=config.AUTO_RAG_RERANK_DROP_RATIO,
                preserve_chunk_ids=preserve_ids,
                preserve_doc_shorts=set(doc_filter or []),
            )
            if debug is not None:
                selected_ids = {hit.id for hit in fused_hits}
                debug.final_hits = [hit for hit in debug.final_hits if hit.chunk_id in selected_ids]
                debug.auto_cutoff = cutoff
        if debug is not None and graph_result is not None:
            debug.graph_result = graph_result

        chunks = [_hit_to_chunk(hit) for hit in fused_hits]
        evidence_result = evaluate_registry_evidence(
            question,
            chunks,
            policy_generation=policy_generation,
            registry=get_default_ontology_registry(),
        )
        if evidence_result is not None:
            chunks = list(evidence_result.selected_chunks)
        clause_detail_rows = self._clause_detail_manifest_rows(
            question,
            _clause_detail_categories(question),
            doc_filter,
        )

        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000
        deterministic_answer = (
            evidence_result.answer
            if evidence_result is not None
            else _deterministic_guard_answer(
                question,
                chunks,
                graph_context=graph_context,
                clause_detail_rows=clause_detail_rows,
                graph_result=graph_result,
                table_store=self._table_store,
            )
        )
        if deterministic_answer:
            answer_text = append_retrieved_source_citations(deterministic_answer, chunks)
            answer_text = append_evidence_validation_warning(answer_text, question, chunks)
            total_ms = (time.perf_counter() - total_started) * 1000
            return RagAnswer(
                answer=_normalize_answer_text(answer_text),
                chunks=chunks,
                timing={
                    "retrieve_ms": retrieve_ms,
                    "llm_ms": 0.0,
                    "total_ms": total_ms,
                },
                debug=debug,
            )

        prompt = self.build_prompt(question, chunks, graph_context=graph_context)

        llm_started = time.perf_counter()
        answer_text = self.llm.generate(prompt, system=SYSTEM_PROMPT, temperature=temperature)
        answer_text = _normalize_answer_text(answer_text)
        answer_text = append_retrieved_source_citations(answer_text, chunks)
        answer_text = append_evidence_validation_warning(answer_text, question, chunks)
        llm_ms = (time.perf_counter() - llm_started) * 1000
        total_ms = (time.perf_counter() - total_started) * 1000

        return RagAnswer(
            answer=answer_text,
            chunks=chunks,
            timing={
                "retrieve_ms": retrieve_ms,
                "llm_ms": llm_ms,
                "total_ms": total_ms,
            },
            debug=debug,
        )
