"""검색과 LLM 생성을 연결하는 RAG 파이프라인."""

from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass

from src import config
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.parser.chunker import Chunk
from src.rag.table_store import TableStore
from src.retrieval import Hit
from src.retrieval.hybrid import rrf_fuse
from src.retrieval.reranker import build_reranker


_CODE_PATTERN = re.compile(r"(?<![A-Z0-9.])(?:[A-Z]\d{2}(?:\.\d{1,2})?|[A-Z]{1,3}\d{2,5})(?![A-Z0-9.])")
_SURGERY_QUERY_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9 ·∙/()_-]{3,})\s*의\s*(?:[^?]{0,40}?)?(?:수술종수|수술해설|수술방법|수술 방법|수술종류|수술 종류|분류)",
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


def _extract_surgery_name_from_query(question: str) -> str | None:
    """수술명 관련 질의에서 핵심 수술명 문자열을 추출한다."""

    for pattern in (_SURGERY_QUERY_PATTERN, _SURGERY_DESC_PATTERN):
        match = pattern.search(question)
        if not match:
            continue
        candidate = match.group(1).strip()
        # 비수술 문항 오탐을 줄이기 위해 수술명 형태(수술 포함 또는 ...술)를 요구한다.
        if "수술" in candidate or candidate.endswith("술"):
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
            for row in rows:
                if not isinstance(row, dict):
                    continue
                surgery_cell = str(row.get("수술명", "")).strip()
                if not surgery_cell:
                    continue
                if surgery_name in surgery_cell or surgery_cell in surgery_name:
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
                    if query_name in cell or cell in query_name:
                        has_match = True
                        break

        if has_match:
            matched.append(hit)
        else:
            unmatched.append(hit)

    return matched + unmatched


def _is_low_value_wide_range(hit: Hit) -> bool:
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

    def retrieve_hits(
        self,
        question: str,
        top_k: int | None = None,
        doc_filter: list[str] | None = None,
        return_debug: bool = False,
    ) -> tuple[list[Hit], DebugInfo | None]:
        """질문에 대한 최종 검색 후보를 반환한다."""

        final_top_k = top_k or self.top_k_final
        retrieval_query = _expand_retrieval_query(question)
        query_embedding = self.embedder.embed_query(retrieval_query)
        query_codes = _extract_query_codes(question)
        named_code_terms = _extract_named_code_terms(question)
        surgery_name = _extract_surgery_name_from_query(question)
        code_hits: list[Hit] = []

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
        reranker_enabled = self.reranker is not None and getattr(self.reranker, "enabled", True)
        rrf_top_k = final_top_k * 2 if reranker_enabled else final_top_k
        if surgery_name:
            # 수술명 질의는 인접 페이지 표가 섞이기 쉬워 부스팅 전에 후보 풀을 확장한다.
            rrf_top_k = max(rrf_top_k, final_top_k * 3)
        fused_hits = rrf_fuse(dense_hits, bm25_hits, top_k=rrf_top_k, rrf_k=self.rrf_k)
        debug_rrf = list(fused_hits)
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

        if self.reranker is not None:
            final_hits = self.reranker.rerank(question, fused_hits, top_k=final_top_k)
        else:
            final_hits = fused_hits[:final_top_k]
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

        fused_hits, debug = self.retrieve_hits(
            question,
            top_k=top_k,
            doc_filter=doc_filter,
            return_debug=return_debug,
        )
        chunks = [_hit_to_chunk(hit) for hit in fused_hits]

        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000
        prompt = build_user_prompt(question, chunks)
        structured_ctx = _build_structured_context(question, chunks, table_store=self._table_store)
        if structured_ctx:
            prompt = f"{structured_ctx}\n\n{prompt}"

        llm_started = time.perf_counter()
        answer_text = self.llm.generate(prompt, system=SYSTEM_PROMPT, temperature=temperature)
        answer_text = append_retrieved_source_citations(answer_text, chunks)
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
