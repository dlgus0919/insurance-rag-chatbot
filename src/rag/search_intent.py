"""Lightweight search intent classification for RAG retrieval routing."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


_CODE_PATTERN = re.compile(
    r"(?<![A-Z0-9.])(?:[A-Z]\d{2}(?:\.\d{1,2})?|[A-Z]{1,3}\d{2,5})(?![A-Z0-9.])",
    re.IGNORECASE,
)
_CLAUSE_PATTERN = re.compile(r"(?:제\s*\d+\s*조|별표\s*\d+|\d+\s*(?:번\s*)?(?:조항|항목|항)\b)")


@dataclass(frozen=True)
class SearchIntentPlan:
    """Retrieval strategy selected before BM25/Chroma execution."""

    intent: str
    confidence: float
    dense_weight: float
    bm25_weight: float
    top_k_dense: int
    top_k_bm25: int
    skip_dense: bool = False
    skip_bm25: bool = False
    exact_terms: list[str] = field(default_factory=list)
    reason: str = ""

    def to_payload(self) -> dict:
        """Return a JSON-serializable diagnostics payload."""

        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 3)
        payload["dense_weight"] = round(float(self.dense_weight), 3)
        payload["bm25_weight"] = round(float(self.bm25_weight), 3)
        return payload


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _code_terms(question: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for match in _CODE_PATTERN.findall(question.upper()):
        if match not in seen:
            seen.add(match)
            terms.append(match)
    return terms


def classify_search_intent(
    question: str,
    *,
    doc_filter: list[str] | None = None,
    default_top_k_dense: int = 12,
    default_top_k_bm25: int = 12,
) -> SearchIntentPlan:
    """Classify a user question into a retrieval strategy.

    This classifier is intentionally rule-based. It runs before embedding search,
    so exact code/clause lookups can avoid unnecessary dense retrieval work.
    """

    text = question.strip()
    compact = re.sub(r"\s+", "", text)
    codes = _code_terms(text)

    if codes:
        return SearchIntentPlan(
            intent="exact_code_lookup",
            confidence=0.95,
            dense_weight=0.15,
            bm25_weight=0.85,
            top_k_dense=max(2, default_top_k_dense // 3),
            top_k_bm25=max(default_top_k_bm25, 16),
            skip_dense=True,
            exact_terms=codes,
            reason="질문에서 코드 패턴을 감지해 BM25 키워드 검색을 우선합니다.",
        )

    if _CLAUSE_PATTERN.search(text) or _contains_any(compact, ("조항", "별표", "약관본문", "면책조항")):
        return SearchIntentPlan(
            intent="clause_or_appendix_lookup",
            confidence=0.88,
            dense_weight=0.25,
            bm25_weight=0.75,
            top_k_dense=max(4, default_top_k_dense // 2),
            top_k_bm25=max(default_top_k_bm25, 16),
            reason="조문/별표/약관 번호성 표현을 감지해 BM25 비중을 높입니다.",
        )

    if _contains_any(compact, ("문서별", "출처별", "기준별", "각각", "비교", "차이")) or (doc_filter and len(doc_filter) >= 2):
        return SearchIntentPlan(
            intent="cross_doc_compare",
            confidence=0.82,
            dense_weight=0.5,
            bm25_weight=0.5,
            top_k_dense=max(default_top_k_dense, 14),
            top_k_bm25=max(default_top_k_bm25, 14),
            reason="복수 문서 비교 의도를 감지해 양쪽 검색을 균형 있게 사용합니다.",
        )

    if _contains_any(compact, ("수가코드", "수가", "점수", "수술종수", "수술분류", "분류표", "수술명")):
        return SearchIntentPlan(
            intent="procedure_code_lookup",
            confidence=0.8,
            dense_weight=0.35,
            bm25_weight=0.65,
            top_k_dense=default_top_k_dense,
            top_k_bm25=max(default_top_k_bm25, 16),
            reason="수가/수술분류 질의로 판단해 표·코드 키워드 검색 비중을 높입니다.",
        )

    if _contains_any(compact.lower(), ("mri", "mra", "엠알아이", "엠알에이")):
        return SearchIntentPlan(
            intent="ambiguous_medical_term",
            confidence=0.76,
            dense_weight=0.72,
            bm25_weight=0.28,
            top_k_dense=max(default_top_k_dense, 14),
            top_k_bm25=max(6, default_top_k_bm25 // 2),
            reason="사용자 표현이 MRI/MRA 등 약관 canonical 용어와 다를 수 있어 의미 기반 검색을 우선합니다.",
        )

    if _contains_any(
        compact,
        (
            "보상돼",
            "보장돼",
            "돈나오",
            "지급돼",
            "가능해",
            "실손",
            "실비",
            "특약",
            "통원",
            "입원",
            "처방조제",
        ),
    ):
        return SearchIntentPlan(
            intent="coverage_judgment",
            confidence=0.78,
            dense_weight=0.7,
            bm25_weight=0.3,
            top_k_dense=max(default_top_k_dense, 14),
            top_k_bm25=max(6, default_top_k_bm25 // 2),
            reason="보상 가능 여부 질의로 판단해 의미 기반 Chroma 검색 비중을 높입니다.",
        )

    if _contains_any(compact.lower(), ("도수", "충격파", "체외충격파")):
        return SearchIntentPlan(
            intent="ambiguous_medical_term",
            confidence=0.72,
            dense_weight=0.72,
            bm25_weight=0.28,
            top_k_dense=max(default_top_k_dense, 14),
            top_k_bm25=max(6, default_top_k_bm25 // 2),
            reason="사용자 표현이 약관 canonical 용어와 다를 수 있어 의미 기반 검색을 우선합니다.",
        )

    return SearchIntentPlan(
        intent="general_explanation",
        confidence=0.62,
        dense_weight=0.6,
        bm25_weight=0.4,
        top_k_dense=default_top_k_dense,
        top_k_bm25=default_top_k_bm25,
        reason="정확 코드/조문 단서가 없어 일반 설명형 검색 전략을 적용합니다.",
    )
