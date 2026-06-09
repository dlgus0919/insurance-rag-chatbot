"""Lightweight search intent classification for RAG retrieval routing."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


_CODE_PATTERN = re.compile(
    r"(?<![A-Z0-9.])(?:[A-Z]\d{2}(?:\.\d{1,2})?|[A-Z]{1,3}\d{2,5})(?![A-Z0-9.])",
    re.IGNORECASE,
)
_NUMERIC_CODE_PATTERN = re.compile(r"(?<![\d.,])\d{4,5}(?![\d.,])")
_CLAUSE_PATTERN = re.compile(r"(?:제\s*\d+\s*조|별표\s*\d+|\d+\s*(?:번\s*)?(?:조항|항목|항)\b)")
_NUMERIC_CODE_CUES = ("코드", "수가", "표준", "EDI", "비급여표준", "행위")
_COVERAGE_CUES = (
    "보상",
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
)
_CLAUSE_DETAIL_CUES = (
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
)
_RIDER_OR_COVERAGE_UNIT_CUES = ("특별약관", "특약", "담보", "진단비", "지원금")


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
    skip_general_dense: bool = False
    exact_terms: list[str] = field(default_factory=list)
    has_exact_code: bool = False
    requires_coverage_judgment: bool = False
    requires_clause_lookup: bool = False
    requires_cross_document: bool = False
    has_ambiguous_term: bool = False
    rule_strength: float = 0.0
    reason: str = ""

    def to_payload(self) -> dict:
        """Return a JSON-serializable diagnostics payload."""

        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 3)
        payload["rule_strength"] = round(float(self.rule_strength or self.confidence), 3)
        payload["dense_weight"] = round(float(self.dense_weight), 3)
        payload["bm25_weight"] = round(float(self.bm25_weight), 3)
        return payload


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def extract_code_terms(question: str) -> list[str]:
    """Extract explicit medical/fee code terms without expanding external ontologies."""

    seen: set[str] = set()
    terms: list[str] = []
    for match in _CODE_PATTERN.findall(question.upper()):
        if match not in seen:
            seen.add(match)
            terms.append(match)
    compact_upper = re.sub(r"\s+", "", question.upper())
    if any(cue.upper() in compact_upper for cue in _NUMERIC_CODE_CUES):
        for match in _NUMERIC_CODE_PATTERN.findall(question):
            suffix = question[question.find(match) + len(match): question.find(match) + len(match) + 3]
            if any(unit in suffix for unit in ("원", "만원", "회", "%", "세대")):
                continue
            if match not in seen:
                seen.add(match)
                terms.append(match)
    return terms


def _code_terms(question: str) -> list[str]:
    return extract_code_terms(question)


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
    lower_compact = compact.lower()
    codes = _code_terms(text)
    has_clause = bool(
        _CLAUSE_PATTERN.search(text)
        or _contains_any(compact, ("조항", "별표", "약관본문", "면책조항", "약관근거"))
    )
    has_clause_detail = _contains_any(compact, _CLAUSE_DETAIL_CUES)
    has_rider_or_coverage_unit = _contains_any(compact, _RIDER_OR_COVERAGE_UNIT_CUES)
    requires_cross_doc = _contains_any(compact, ("문서별", "출처별", "기준별", "각각", "비교", "차이")) or bool(doc_filter and len(doc_filter) >= 2)
    requires_coverage = _contains_any(compact, _COVERAGE_CUES)
    has_ambiguous = _contains_any(lower_compact, ("mri", "mra", "엠알아이", "엠알에이")) or _contains_any(
        compact.lower(),
        ("도수", "충격파", "체외충격파"),
    )

    if codes:
        compound = requires_coverage or has_clause or requires_cross_doc
        return SearchIntentPlan(
            intent="exact_code_compound_lookup" if compound else "exact_code_lookup",
            confidence=0.92 if compound else 0.95,
            dense_weight=0.45 if compound else 0.35,
            bm25_weight=0.55 if compound else 0.65,
            top_k_dense=default_top_k_dense if compound else max(4, default_top_k_dense // 2),
            top_k_bm25=max(default_top_k_bm25, 16),
            skip_dense=False,
            skip_general_dense=not compound,
            exact_terms=codes,
            has_exact_code=True,
            requires_coverage_judgment=requires_coverage,
            requires_clause_lookup=has_clause,
            requires_cross_document=requires_cross_doc,
            has_ambiguous_term=has_ambiguous,
            rule_strength=0.92 if compound else 0.95,
            reason=(
                "질문에서 코드와 보상/약관 판단 단서를 함께 감지해 코드 필터 검색과 의미 검색을 모두 유지합니다."
                if compound
                else "질문에서 코드 패턴을 감지해 코드 필터 검색과 BM25를 우선합니다."
            ),
        )

    if has_clause_detail and (has_rider_or_coverage_unit or has_clause or requires_coverage):
        return SearchIntentPlan(
            intent="clause_detail_lookup",
            confidence=0.86,
            dense_weight=0.32,
            bm25_weight=0.68,
            top_k_dense=max(default_top_k_dense, 14),
            top_k_bm25=max(default_top_k_bm25, 24),
            requires_clause_lookup=True,
            requires_coverage_judgment=requires_coverage,
            rule_strength=0.86,
            reason="담보/특약의 진단확정·청구서류·자기부담금 등 조항 세부 질의를 감지해 BM25와 문서 내부 보강 검색을 우선합니다.",
        )

    if has_clause:
        return SearchIntentPlan(
            intent="clause_or_appendix_lookup",
            confidence=0.88,
            dense_weight=0.25,
            bm25_weight=0.75,
            top_k_dense=max(4, default_top_k_dense // 2),
            top_k_bm25=max(default_top_k_bm25, 16),
            requires_clause_lookup=True,
            rule_strength=0.88,
            reason="조문/별표/약관 번호성 표현을 감지해 BM25 비중을 높입니다.",
        )

    if requires_cross_doc:
        return SearchIntentPlan(
            intent="cross_doc_compare",
            confidence=0.82,
            dense_weight=0.5,
            bm25_weight=0.5,
            top_k_dense=max(default_top_k_dense, 14),
            top_k_bm25=max(default_top_k_bm25, 14),
            requires_cross_document=True,
            rule_strength=0.82,
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
            rule_strength=0.8,
            reason="수가/수술분류 질의로 판단해 표·코드 키워드 검색 비중을 높입니다.",
        )

    if _contains_any(lower_compact, ("mri", "mra", "엠알아이", "엠알에이")):
        return SearchIntentPlan(
            intent="ambiguous_medical_term",
            confidence=0.76,
            dense_weight=0.72,
            bm25_weight=0.28,
            top_k_dense=max(default_top_k_dense, 14),
            top_k_bm25=max(6, default_top_k_bm25 // 2),
            has_ambiguous_term=True,
            rule_strength=0.76,
            reason="사용자 표현이 MRI/MRA 등 약관 canonical 용어와 다를 수 있어 의미 기반 검색을 우선합니다.",
        )

    if requires_coverage:
        return SearchIntentPlan(
            intent="coverage_judgment",
            confidence=0.78,
            dense_weight=0.7,
            bm25_weight=0.3,
            top_k_dense=max(default_top_k_dense, 14),
            top_k_bm25=max(6, default_top_k_bm25 // 2),
            requires_coverage_judgment=True,
            rule_strength=0.78,
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
            has_ambiguous_term=True,
            rule_strength=0.72,
            reason="사용자 표현이 약관 canonical 용어와 다를 수 있어 의미 기반 검색을 우선합니다.",
        )

    return SearchIntentPlan(
        intent="general_explanation",
        confidence=0.62,
        dense_weight=0.6,
        bm25_weight=0.4,
        top_k_dense=default_top_k_dense,
        top_k_bm25=default_top_k_bm25,
        rule_strength=0.62,
        reason="정확 코드/조문 단서가 없어 일반 설명형 검색 전략을 적용합니다.",
    )
