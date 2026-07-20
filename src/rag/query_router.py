"""Route a unified general question to an existing retrieval strategy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from src.rag.search_intent import classify_search_intent

QueryRouteName = Literal["general", "quickcode", "formal"]

_QUICKCODE_CUES = (
    "퀵코드",
    "코드검색",
    "코드조회",
    "수가코드",
    "edi코드",
    "행위코드",
    "분류점수",
    "수가점수",
)
_QUICKCODE_SUFFIX_CUES = ("코드알려", "코드찾아", "코드뭐", "코드는")
_FORMAL_KEYWORD_CUES = ("약관에서찾아", "약관검색", "약관키워드", "약관시술명")
_COVERAGE_CUES = ("보상", "보장", "지급", "실손", "실비")
_ARTICLE_NUMBER_RX = re.compile(r"제\s*(\d+)\s*조")


@dataclass(frozen=True)
class QueryRoute:
    """Resolved internal strategy for a user-visible general question."""

    route: QueryRouteName
    intent: str
    filters: dict = field(default_factory=dict)
    formal_mode: str | None = None
    coverage_topics: list[str] = field(default_factory=list)
    article_number: str | None = None
    include_appendix: bool = False
    route_reason: str = "general_default"
    matched_cues: list[str] = field(default_factory=list)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _infer_coverage_topics(question: str) -> list[str]:
    topics = [
        topic
        for topic in ("질병급여", "질병비급여", "3대비급여")
        if topic in question
    ]
    return topics


def _matched_cues(compact: str, cues: tuple[str, ...]) -> list[str]:
    return [cue for cue in cues if cue in compact]


def resolve_query_route(question: str, filters: dict | None = None) -> QueryRoute:
    """Select an existing general, quick-code, or formal retrieval path.

    Explicit legacy modes remain API-compatible. This resolver is only for
    user-visible general questions after the UI modes are unified.
    """

    base_filters = dict(filters or {})
    plan = classify_search_intent(
        question,
        doc_filter=base_filters.get("doc_filter") or base_filters.get("doc_short"),
    )
    compact = _compact(question)
    formal_keyword_cues = _matched_cues(compact, _FORMAL_KEYWORD_CUES)
    quick_cues = _matched_cues(compact, _QUICKCODE_CUES)
    quick_suffix_cues = _matched_cues(compact, _QUICKCODE_SUFFIX_CUES)
    coverage_cues = _matched_cues(compact, _COVERAGE_CUES)
    formal_keyword_lookup = bool(formal_keyword_cues)
    coverage_requested = plan.requires_coverage_judgment or any(cue in compact for cue in _COVERAGE_CUES)
    structured_coverage_requested = coverage_requested and bool(_infer_coverage_topics(question))
    strong_quick_requested = bool(quick_cues)
    suffix_quick_requested = bool(quick_suffix_cues)
    procedure_quick_requested = plan.intent == "procedure_code_lookup" and any(
        cue in compact for cue in ("수가", "점수", "코드")
    )
    quick_requested = (
        strong_quick_requested
        or procedure_quick_requested
        or (suffix_quick_requested and not plan.requires_coverage_judgment)
    )

    if quick_requested and not plan.requires_clause_lookup:
        routed_filters = dict(base_filters)
        routed_filters.setdefault("include_summary", True)
        routed_filters.setdefault("include_coverage", coverage_requested)
        route_reason = "procedure_code_intent" if procedure_quick_requested else "quickcode_cue"
        matched = unique_ordered([*quick_cues, *quick_suffix_cues])
        if procedure_quick_requested:
            matched = unique_ordered([*matched, "procedure_code_lookup"])
        routed_filters.update(
            {
                "_auto_routed": True,
                "_resolved_route": "quickcode",
                "_route_reason": route_reason,
                "_matched_cues": matched,
            }
        )
        return QueryRoute(
            route="quickcode",
            intent=plan.intent,
            filters=routed_filters,
            route_reason=route_reason,
            matched_cues=matched,
        )

    if plan.intent == "policy_attribute_lookup":
        routed_filters = dict(base_filters)
        routed_filters.update(
            {
                "_auto_routed": True,
                "_resolved_route": "general",
                "_route_reason": "policy_attribute_direct_lookup",
                "_matched_cues": ["policy_attribute_lookup"],
            }
        )
        return QueryRoute(
            route="general",
            intent=plan.intent,
            filters=routed_filters,
            route_reason="policy_attribute_direct_lookup",
            matched_cues=["policy_attribute_lookup"],
        )

    if plan.requires_clause_lookup or structured_coverage_requested or formal_keyword_lookup:
        if plan.requires_clause_lookup:
            search_type = "약관 조문 검색"
            formal_mode = "clause_lookup"
        elif formal_keyword_lookup and not plan.requires_coverage_judgment:
            search_type = "키워드/시술명 검색"
            formal_mode = "keyword_search"
        else:
            search_type = "보상가능 여부 판정"
            formal_mode = "coverage_judgment"

        routed_filters = dict(base_filters)
        routed_filters.setdefault("search_type", search_type)
        route_reason = (
            "clause_lookup_intent"
            if plan.requires_clause_lookup
            else "formal_keyword_cue"
            if formal_keyword_lookup and not plan.requires_coverage_judgment
            else "structured_coverage_cue"
        )
        matched = unique_ordered([*formal_keyword_cues, *coverage_cues, *(_infer_coverage_topics(question))])
        routed_filters.update(
            {
                "_auto_routed": True,
                "_resolved_route": "formal",
                "_route_reason": route_reason,
                "_matched_cues": matched,
            }
        )
        article_match = _ARTICLE_NUMBER_RX.search(question)
        return QueryRoute(
            route="formal",
            intent=plan.intent,
            filters=routed_filters,
            formal_mode=formal_mode,
            coverage_topics=_infer_coverage_topics(question),
            article_number=article_match.group(1) if article_match else None,
            include_appendix="별표" in question,
            route_reason=route_reason,
            matched_cues=matched,
        )

    return QueryRoute(route="general", intent=plan.intent, filters=base_filters)


def unique_ordered(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
