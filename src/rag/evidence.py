"""Evidence guardrails for code and source-specific comparison questions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.parser.chunker import Chunk


CODE_PATTERN = re.compile(r"(?<![A-Z0-9.])(?:[A-Z]\d{2}(?:\.\d{1,2})?|[A-Z]{1,3}\d{2,5})(?![A-Z0-9.])")
CLASSIFICATION_PATTERN = re.compile(r"(?:[가-힣]{1,3}|[A-Z])\s*-\s*\d{1,5}")
IMPORTANT_TERM_RE = re.compile(r"[가-힣A-Za-z0-9]+")

STRICT_EVIDENCE_KEYWORDS = (
    "문서별",
    "각각",
    "비교",
    "차이",
    "출처별",
    "기준별",
    "코드",
    "수가",
    "분류번호",
    "지급률",
    "수술종수",
    "수술종류",
    "점수",
)
VALUE_KEYWORDS = ("코드", "수가", "분류번호", "지급률", "수술종수", "수술종류", "점수")
COMPARE_KEYWORDS = ("문서별", "각각", "비교", "차이", "출처별", "기준별")
STOP_TERMS = {
    "문서별",
    "각각",
    "검색",
    "알려주세요",
    "알려줘",
    "대한",
    "코드",
    "수가",
    "분류번호",
    "기준",
    "비교",
    "차이",
    "출처별",
    "기준별",
    "문서",
    "무엇",
    "어떤",
    "해당",
    "확인",
    "주세요",
    "검색하여",
    "문서별로",
    "코드를",
}

TERM_SUFFIXES = ("으로", "에서", "에게", "부터", "까지", "처럼", "로", "을", "를", "은", "는", "이", "가", "에", "의", "도", "만", "와", "과")


@dataclass(frozen=True)
class EvidenceFact:
    """A source-bound value extracted from one retrieved chunk."""

    doc_short: str
    page_label: str
    code: str
    description: str
    row_text: str
    classification_no: str | None = None


def is_strict_evidence_query(question: str) -> bool:
    """Return True when answer should preserve source-specific values."""

    compact = re.sub(r"\s+", "", question)
    has_value_keyword = any(keyword in compact for keyword in VALUE_KEYWORDS)
    has_compare_keyword = any(keyword in compact for keyword in COMPARE_KEYWORDS)
    has_code_literal = bool(CODE_PATTERN.search(question.upper()))
    return has_code_literal or has_value_keyword or (has_compare_keyword and any(k in compact for k in STRICT_EVIDENCE_KEYWORDS))


def _page_label(metadata: dict) -> str:
    start = metadata.get("page_start")
    end = metadata.get("page_end")
    if start == end or end is None:
        return f"p.{start}"
    return f"p.{start}-{end}"


def _normalize_query_term(term: str) -> str:
    normalized = term.strip()
    for suffix in TERM_SUFFIXES:
        if len(normalized) > len(suffix) + 1 and normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def _query_terms(question: str) -> list[str]:
    terms: list[str] = []
    for term in IMPORTANT_TERM_RE.findall(question):
        normalized = _normalize_query_term(term)
        if len(normalized) < 2 or normalized in STOP_TERMS:
            continue
        if CODE_PATTERN.fullmatch(normalized.upper()):
            continue
        if normalized not in terms:
            terms.append(normalized)
    return terms[:4]


def _line_window(lines: list[str], index: int) -> str:
    start = max(0, index - 1)
    end = min(len(lines), index + 2)
    return " ".join(line.strip() for line in lines[start:end] if line.strip())


def _matches_query_terms(window: str, terms: list[str]) -> bool:
    if not terms:
        return True
    normalized_window = re.sub(r"\s+", "", window).lower()
    matched = 0
    for term in terms:
        normalized_term = re.sub(r"\s+", "", term).lower()
        if normalized_term and normalized_term in normalized_window:
            matched += 1
    return matched >= min(2, len(terms))


def _clean_row_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _description_for_code(line: str, match: re.Match[str]) -> str:
    before = _clean_row_text(line[: match.start()])
    after = _clean_row_text(line[match.end() :])
    before = CLASSIFICATION_PATTERN.sub("", before).strip()
    if re.search(r"[가-힣A-Za-z]", after):
        return after
    if before:
        return before
    return _clean_row_text(line)


def extract_code_evidence_facts(question: str, chunks: list[Chunk], max_facts: int = 16) -> list[EvidenceFact]:
    """Extract source-bound code rows from retrieved chunks."""

    if not is_strict_evidence_query(question):
        return []

    terms = _query_terms(question)
    facts: list[EvidenceFact] = []
    seen: set[tuple[str, str, str, str]] = set()

    for chunk in chunks:
        metadata = chunk.metadata
        doc_short = str(metadata.get("doc_short") or metadata.get("doc_name") or "문서")
        page_label = _page_label(metadata)
        lines = [line for line in chunk.text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            code_matches = list(CODE_PATTERN.finditer(line.upper()))
            if not code_matches:
                continue
            window = _line_window(lines, index)
            if not _matches_query_terms(line, terms):
                continue
            classification_match = CLASSIFICATION_PATTERN.search(line)
            classification_no = _clean_row_text(classification_match.group(0)) if classification_match else None
            row_text = _clean_row_text(window)
            for match in code_matches:
                code = match.group(0).upper()
                description = _description_for_code(line, match)
                key = (doc_short, page_label, code, description)
                if key in seen:
                    continue
                seen.add(key)
                facts.append(
                    EvidenceFact(
                        doc_short=doc_short,
                        page_label=page_label,
                        code=code,
                        description=description,
                        row_text=row_text,
                        classification_no=classification_no,
                    )
                )
                if len(facts) >= max_facts:
                    return facts
    return facts


def build_strict_evidence_context(question: str, chunks: list[Chunk]) -> str | None:
    """Build a compact evidence block that the LLM must use before free-form context."""

    facts = extract_code_evidence_facts(question, chunks)
    if not facts:
        return None

    lines = [
        "[구조화 근거 — 문서별 코드/수치 검증]",
        "아래 값은 검색 청크에서 문서별로 추출한 근거입니다. 문서별 값이 다르면 절대 통일하지 말고 그대로 분리해 답하세요.",
        "분류번호와 코드를 구분하고, 같은 행의 코드와 명칭만 연결하세요.",
    ]
    for fact in facts:
        classification = f" | 분류번호: {fact.classification_no}" if fact.classification_no else ""
        lines.append(
            f"- 문서: {fact.doc_short} | 페이지: {fact.page_label}{classification} | 코드: {fact.code} | 명칭/행: {fact.description}"
        )
    return "\n".join(lines)


def append_evidence_validation_warning(answer: str, question: str, chunks: list[Chunk]) -> str:
    """Append a warning when answer claims a source-code pair absent from extracted evidence."""

    facts = extract_code_evidence_facts(question, chunks)
    if not facts:
        return answer

    valid_by_doc: dict[str, set[str]] = {}
    for fact in facts:
        valid_by_doc.setdefault(fact.doc_short, set()).add(fact.code)

    warnings: list[str] = []
    for line in answer.splitlines():
        line_codes = set(CODE_PATTERN.findall(line.upper()))
        if not line_codes:
            continue
        for doc_short, valid_codes in valid_by_doc.items():
            if doc_short not in line:
                continue
            invalid = sorted(code for code in line_codes if code not in valid_codes)
            if invalid:
                warnings.append(
                    f"{doc_short} 근거에서 확인된 코드는 {', '.join(sorted(valid_codes))}인데, 답변 행에는 {', '.join(invalid)}가 포함되어 있습니다."
                )

    if not warnings:
        return answer
    unique_warnings = list(dict.fromkeys(warnings))
    warning_block = "\n".join(f"- {warning}" for warning in unique_warnings)
    return f"{answer.rstrip()}\n\n[근거 검증 경고]\n{warning_block}"
