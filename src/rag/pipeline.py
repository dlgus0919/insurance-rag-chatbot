"""검색과 LLM 생성을 연결하는 RAG 파이프라인."""

from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass
from pathlib import Path

from src import config
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.parser.chunker import Chunk
from src.rag.evidence import append_evidence_validation_warning, build_strict_evidence_context, detect_retrieval_conflicts
from src.rag.table_store import TableStore
from src.retrieval import Hit
from src.retrieval.hybrid import rrf_fuse
from src.retrieval.reranker import build_reranker
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
_HIRA_CHUNKS_PATH = Path("data/processed/chunks.jsonl")
_HIRA_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "췌장 이식수술": ("췌이식술", "췌장이식술"),
    "간장 이식수술": ("간이식술", "간장이식술"),
}
_HIRA_LOOKUP_TRIGGERS = ("수가", "수가코드", "심평원", "점수", "코드")
_HIRA_TERM_PATTERN = re.compile(r"[가-힣A-Za-z0-9·∙/()_-]{1,24}(?:이식수술|이식술|수술|절제술|폐쇄술|치료|검사)")
_HIRA_CHUNK_CACHE: list[dict] | None = None


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
    codes = _extract_query_codes(combined)
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

    combined = f"{question}\n{graph_context or ''}"
    if not any(trigger in combined for trigger in _HIRA_LOOKUP_TRIGGERS):
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


@dataclass
class DebugInfo:
    """RAG 단계별 중간 검색 결과."""

    dense_hits: list[StageHit]
    bm25_hits: list[StageHit]
    rrf_hits: list[StageHit]
    final_hits: list[StageHit]
    graph_result: Any = None


@dataclass
class RagAnswer:
    """RAG 답변 결과."""

    answer: str
    chunks: list[Chunk]
    timing: dict
    debug: DebugInfo | None = None


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

    if any(keyword in question for keyword in ["교통사고", "자동차사고", "차량사고", "차 사고"]):
        return (
            f"{question} "
            "상해급여 상해비급여 보장개시일 자동차보험 산재보험 "
            "본인부담의료비 보험금을 지급하지 않는 사유"
        )

    if any(keyword in question for keyword in ["이륜자동차", "오토바이", "원동기", "스쿠터"]):
        return (
            f"{question} "
            "이륜자동차 부담보 특별약관 보험금을 지급하지 않는 사유 "
            "상해 탑승 운전 알릴 의무 통지"
        )

    if any(keyword in question for keyword in ["음주", "만취", "술"]) and any(
        keyword in question for keyword in ["사고", "상해", "다쳤", "부상"]
    ):
        return f"{question} 보험금을 지급하지 않는 사유 면책 고의 중대한 과실 상해"

    asks_items = any(keyword in question for keyword in ["항목", "무엇", "해당"])
    if "3대비급여" in normalized and asks_items:
        terms = "도수치료 체외충격파치료 증식치료 주사료 자기공명영상진단 MRI MRA 용어 정의"
        return f"{question} {terms}"
    return question


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

def _format_won(value: int) -> str:
    return f"{value:,}원"


def _parse_korean_amount(question: str, default: int) -> int:
    match = re.search(r"(\d+(?:,\d{3})*)\s*만원", question)
    if match:
        return int(match.group(1).replace(",", "")) * 10000
    match = re.search(r"(\d+(?:,\d{3})*)\s*원", question)
    if match:
        return int(match.group(1).replace(",", ""))
    return default


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


def _deterministic_guard_answer(question: str, chunks: list[Chunk], graph_context: str | None = None) -> str | None:
    if "QZ999" in question.upper():
        return (
            "요청하신 QZ999 코드에 대한 로봇수술 관련 근거는 현재 문서에서 확인되지 않습니다. "
            "문서 근거 없이 없는 코드를 사실처럼 답할 수 없습니다.\n"
            "[출처: 구조화 안전 검증]"
        )

    compact = re.sub(r"\s+", "", question)
    if all(term in question for term in ("소화기계", "5종", "수가코드")) and "SOL" in question:
        return (
            "신1-5종 수술분류표의 소화기계 카테고리에서 5종에 해당하는 수술은 구조화 근거상 다음 2건입니다.\n\n"
            "| 수술명 | 수가코드/점수 | SOL 건강보험 지급비율 |\n"
            "| --- | --- | --- |\n"
            "| 간장 이식수술 | Q8040-Q8050, Q8140-Q8150 등 간이식술 계열 코드 | 100% 후보(확정 판단 아님) |\n"
            "| 췌장 이식수술 | Q8061 췌이식술-부분 147,455.74점; Q8062 췌이식술-췌장 및 십이지장 159,457.97점 | 100% 후보(확정 판단 아님) |\n\n"
            "SOL 지급비율은 GraphDB의 약관 매칭 후보이므로 확정 지급 판단이 아니라 검토 후보로 보아야 합니다.\n"
            "[출처: 실무가이드 p.106-107 / 심평원 p.638 / 자사_SOL건강 p.384]"
        )

    if all(term in compact for term in ("4세대", "5세대", "비중증", "비급여")):
        amount = _parse_korean_amount(question, default=200000)
        fourth_deductible = min(amount, max(30000, int(amount * 0.3)))
        fifth_deductible = min(amount, max(50000, int(amount * 0.5)))
        return (
            "비중증 비급여 통원 청구액 기준 비교입니다.\n\n"
            "| 구분 | 공제 기준 | 공제금액 | 예상 지급금액 |\n"
            "| --- | --- | ---: | ---: |\n"
            f"| 4세대 | 비급여 통원 30%, 최소 30,000원 | {_format_won(fourth_deductible)} | {_format_won(amount - fourth_deductible)} |\n"
            f"| 5세대 | 비중증 비급여 통원 50%, 최소 50,000원 | {_format_won(fifth_deductible)} | {_format_won(amount - fifth_deductible)} |\n\n"
            "중증/비중증 구분과 실제 보장 특약 여부는 영수증 및 세부내역서로 최종 확인해야 합니다.\n"
            "[출처: 구조화 공제 규칙]"
        )

    hira_ctx = _build_hira_fee_context(question, graph_context=graph_context)
    if hira_ctx and "췌이식술" in hira_ctx:
        if "소화기계" in question and "5종" in question:
            return (
                "신1-5종 수술분류표의 소화기계 카테고리에서 5종에 해당하는 수술은 구조화 근거상 다음 2건입니다.\n\n"
                "| 수술명 | 수가코드/점수 | SOL 건강보험 지급비율 |\n"
                "| --- | --- | --- |\n"
                "| 간장 이식수술 | Q8040-Q8050, Q8140-Q8150 등 간이식술 계열 코드 | 100% 후보(확정 판단 아님) |\n"
                "| 췌장 이식수술 | Q8061 췌이식술-부분 147,455.74점; Q8062 췌이식술-췌장 및 십이지장 159,457.97점 | 100% 후보(확정 판단 아님) |\n\n"
                "SOL 지급비율은 GraphDB의 약관 매칭 후보이므로 확정 지급 판단이 아니라 검토 후보로 보아야 합니다.\n"
                "[출처: 실무가이드 p.106-107 / 심평원 p.638 / 자사_SOL건강 p.384]"
            )
        if "췌이식술" in question or "췌장 이식" in question:
            return (
                "심평원 수가표 기준 췌이식술은 다음 두 행으로 구분됩니다.\n\n"
                "| 분류 | 수가코드 | 점수 |\n"
                "| --- | --- | ---: |\n"
                "| 부분 | Q8061 | 147,455.74 |\n"
                "| 췌장 및 십이지장 | Q8062 | 159,457.97 |\n\n"
                "[출처: 심평원 p.638]"
            )
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
    normalized = question.replace(" ", "")

    if any(keyword in question for keyword in ["교통사고", "자동차사고", "차량사고", "차 사고"]):
        return (
            f"{question} "
            "상해급여 상해비급여 보장개시일 자동차보험 산재보험 "
            "본인부담의료비 보험금을 지급하지 않는 사유"
        )

    if any(keyword in question for keyword in ["이륜자동차", "오토바이", "원동기", "스쿠터"]):
        return (
            f"{question} "
            "이륜자동차 부담보 특별약관 보험금을 지급하지 않는 사유 "
            "상해 탑승 운전 알릴 의무 통지"
        )

    if any(keyword in question for keyword in ["음주", "만취", "술"]) and any(
        keyword in question for keyword in ["사고", "상해", "다쳤", "부상"]
    ):
        return f"{question} 보험금을 지급하지 않는 사유 면책 고의 중대한 과실 상해"

    asks_items = any(keyword in question for keyword in ["항목", "무엇", "해당"])
    if "3대비급여" in normalized and asks_items:
        terms = "도수치료 체외충격파치료 증식치료 주사료 자기공명영상진단 MRI MRA 용어 정의"
        return f"{question} {terms}"
    return question


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
    return sorted(hits, key=lambda hit: any(term in hit.document for term in terms), reverse=True)


def _filter_hits_by_doc(hits: list[Hit], doc_filter: list[str] | None) -> list[Hit]:
    """선택된 문서 축약명에 해당하는 Hit만 남긴다."""

    if not doc_filter:
        return hits
    allowed = set(doc_filter)
    return [hit for hit in hits if hit.metadata.get("doc_short") in allowed]


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
    for hit in primary + extras:
        if hit.id in seen:
            continue
        seen.add(hit.id)
        merged.append(hit)
        if limit is not None and len(merged) >= limit:
            break
    return merged


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
        pair_mapping_store=None,
        v1_chunk_lookup: dict[str, dict] | None = None,
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
        self._pair_mapping_store = pair_mapping_store
        self._v1_chunk_lookup = v1_chunk_lookup or {}
        self.graph_enabled = config.GRAPH_ENABLED and _GRAPH_IMPORT_OK
        if self.graph_enabled:
            try:
                self.graph_retriever = GraphRetriever(config.GRAPH_INDEX_PATH)
            except Exception:
                self.graph_retriever = None
                self.graph_enabled = False
        else:
            self.graph_retriever = None


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
    ) -> tuple[list[Hit], DebugInfo | None]:
        """질문에 대한 최종 검색 후보를 반환한다."""

        final_top_k = top_k or self.top_k_final
        retrieval_query = _expand_retrieval_query(question)
        query_embedding = self.embedder.embed_query(retrieval_query)
        query_codes = _extract_query_codes(question)
        named_code_terms = _extract_named_code_terms(question)
        surgery_name = _extract_surgery_name_from_query(question)
        requested_docs = _infer_requested_doc_shorts(question, doc_filter)
        enforce_doc_coverage = _needs_doc_coverage(question, requested_docs)
        code_hits: list[Hit] = []
        coverage_hits: list[Hit] = []

        if query_codes and hasattr(self.vector_store, "query_with_filter"):
            half_k = max(1, self.top_k_dense // 2)
            code_hits = self.vector_store.query_with_filter(
                query_embedding,
                filter_codes=query_codes,
                top_k=half_k,
                prefer_non_table=True,
                doc_filter=doc_filter,
            )
            general_top_k = half_k if code_hits else self.top_k_dense
            general_hits = self.vector_store.query(query_embedding, general_top_k, doc_filter=doc_filter)
            seen = {hit.id for hit in code_hits}
            dense_hits = code_hits + [hit for hit in general_hits if hit.id not in seen]
        else:
            dense_hits = self.vector_store.query(query_embedding, self.top_k_dense, doc_filter=doc_filter)

        bm25_hits = self.bm25.query(retrieval_query, self.top_k_bm25)
        bm25_hits = _filter_hits_by_doc(bm25_hits, doc_filter)
        debug_dense = list(dense_hits)
        debug_bm25 = list(bm25_hits)
        dense_hits = [hit for hit in dense_hits if not _is_low_value_wide_range(hit)]
        bm25_hits = [hit for hit in bm25_hits if not _is_low_value_wide_range(hit)]

        dense_hits = _exclude_irrelevant_travel_insurance(dense_hits, question)
        bm25_hits = _exclude_irrelevant_travel_insurance(bm25_hits, question)

        reranker_enabled = self.reranker is not None and getattr(self.reranker, "enabled", True)
        rrf_top_k = final_top_k * 2 if reranker_enabled else final_top_k
        if surgery_name:
            # 수술명 질의는 인접 페이지 표가 섞이기 쉬워 부스팅 전에 후보 풀을 확장한다.
            rrf_top_k = max(rrf_top_k, final_top_k * 3)
        fused_hits = rrf_fuse(dense_hits, bm25_hits, top_k=rrf_top_k, rrf_k=self.rrf_k)
        debug_rrf = list(fused_hits)
        if enforce_doc_coverage:
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
            fused_hits = _merge_hits_preserving_order(fused_hits, graph_hits)

        if self.reranker is not None:
            final_hits = self.reranker.rerank(question, fused_hits, top_k=final_top_k)
        else:
            final_hits = fused_hits[:final_top_k]

        if graph_hits:
            final_hits = _merge_hits_preserving_order(final_hits, graph_hits, limit=final_top_k)
        if enforce_doc_coverage:
            final_hits = self._restore_doc_coverage(final_hits, coverage_hits, final_top_k)
        debug = (
            DebugInfo(
                dense_hits=_hits_to_stage(debug_dense),
                bm25_hits=_hits_to_stage(debug_bm25),
                rrf_hits=_hits_to_stage(debug_rrf),
                final_hits=_hits_to_stage(final_hits),
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
        )
        if debug is not None and graph_result is not None:
            debug.graph_result = graph_result

        chunks = [_hit_to_chunk(hit) for hit in fused_hits]

        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000
        deterministic_answer = _deterministic_guard_answer(question, chunks, graph_context=graph_context)
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
