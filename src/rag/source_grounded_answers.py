"""Source-grounded deterministic answer helpers for RAG guard paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.claim_calculation.deductible_rules import DeductibleRule, lookup_rule
from src.ontology.registry import OntologyConcept, OntologyRegistry, get_default_ontology_registry
from src.parser.chunker import Chunk


_CODE_PATTERN = re.compile(r"(?<![A-Z0-9.])(?:[A-Z]\d{2}(?:\.\d{1,2})?|[A-Z]{1,3}\d{2,5})(?![A-Z0-9.])")
_HIRA_CODE_SEGMENT_PATTERN = re.compile(r"\b(?P<code>[A-Z]\d{4})\b\s*(?P<body>.*)")
_HIRA_SCORE_PATTERN = re.compile(r"(?P<score>\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*점")


@dataclass(frozen=True)
class PolicyClauseDecision:
    """A source-backed policy decision rendered independently from GraphDB paths."""

    answer: str
    payload: dict[str, Any]
    chunks: list[Chunk]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _source_evidence(chunk: Chunk) -> dict[str, Any]:
    metadata = chunk.metadata or {}
    return {
        "doc_short": metadata.get("doc_short") or "문서",
        "page_start": metadata.get("page_start"),
        "page_end": metadata.get("page_end", metadata.get("page_start")),
        "chunk_id": chunk.id,
        "is_own_company": metadata.get("is_own_company"),
    }


def _hair_loss_profile(
    question: str,
    registry: OntologyRegistry,
) -> tuple[OntologyConcept, dict[str, Any]] | None:
    compact_question = _compact(question)
    for concept in registry.concepts:
        profile = concept.properties.get("source_grounded_decision")
        if not isinstance(profile, dict):
            continue
        question_terms = [str(term).strip() for term in profile.get("question_terms", [])]
        if any(_compact(term) and _compact(term) in compact_question for term in question_terms):
            return concept, profile
    return None


def _selected_policy_chunks(chunks: list[Chunk], policy_generation: str) -> list[Chunk]:
    return [
        chunk
        for chunk in chunks
        if str((chunk.metadata or {}).get("policy_generation") or "") == policy_generation
    ]


def _direct_clause_chunks(
    chunks: list[Chunk],
    evidence_terms: list[str],
    preferred_chunk_ids: list[str] | None = None,
) -> list[Chunk]:
    compact_terms = [_compact(term) for term in evidence_terms if _compact(term)]
    if not compact_terms:
        return []
    direct_chunks = [
        chunk
        for chunk in chunks
        if all(term in _compact(chunk.text) for term in compact_terms)
    ]
    preferred = set(preferred_chunk_ids or [])
    preferred_chunks = [chunk for chunk in direct_chunks if chunk.id in preferred]
    return preferred_chunks or direct_chunks


def _matches_any_term(question: str, terms: list[str]) -> bool:
    compact_question = _compact(question)
    return any(_compact(term) and _compact(term) in compact_question for term in terms)


def _authority_note(
    policy_generation: str,
    direct_chunks: list[Chunk],
    profile: dict[str, Any],
) -> str:
    if any((chunk.metadata or {}).get("is_own_company") is True for chunk in direct_chunks):
        return f"현재 선택한 {policy_generation.replace('th', '세대')} 자사 약관의 직접 조항 근거입니다."
    standard_note = str(profile.get("standard_reference_note") or "").strip()
    if policy_generation == "5th" and standard_note:
        return standard_note
    return f"현재 선택한 {policy_generation.replace('th', '세대')} 기준 문서의 직접 조항 근거입니다."


def _join_decision_answer(summary: str, authority_note: str, conditions: list[str]) -> str:
    condition_text = ", ".join(conditions)
    lines = [summary, authority_note]
    if condition_text:
        lines.append(f"확인할 조건: {condition_text}.")
    return "\n\n".join(line for line in lines if line)


def build_policy_clause_decision(
    question: str,
    chunks: list[Chunk],
    *,
    policy_generation: str | None,
    registry: OntologyRegistry | None = None,
) -> PolicyClauseDecision | None:
    """Build a constrained hair-loss decision only from a selected policy clause."""

    if policy_generation not in {"4th", "5th"}:
        return None

    registry = registry or get_default_ontology_registry()
    matched = _hair_loss_profile(question, registry)
    if matched is None:
        return None
    concept, profile = matched
    direct_source_ids = profile.get("direct_source_chunk_ids") or {}
    preferred_chunk_ids = direct_source_ids.get(policy_generation, []) if isinstance(direct_source_ids, dict) else []
    direct_chunks = _direct_clause_chunks(
        _selected_policy_chunks(chunks, policy_generation),
        [str(term) for term in profile.get("evidence_terms", [])],
        [str(chunk_id) for chunk_id in preferred_chunk_ids],
    )
    if not direct_chunks:
        return None

    conditions = [str(item) for item in profile.get("conditions", []) if str(item).strip()]
    questions = list(concept.planner_clarification_questions)
    required_evidence = list(concept.planner_required_evidence)
    authority_note = _authority_note(policy_generation, direct_chunks, profile)

    if _matches_any_term(question, [str(term) for term in profile.get("disease_or_side_effect_terms", [])]):
        status = "clarification_required"
        status_label = "추가 확인 필요"
        summary = str(profile.get("alternative_cause_note") or "").strip()
    elif _matches_any_term(question, [str(term) for term in profile.get("age_related_terms", [])]):
        status = "conditional_exclusion"
        status_label = "조건부 보상 제외 조항 확인"
        summary = str(profile.get("conditional_exclusion_summary") or "").strip()
    else:
        status = "clarification_required"
        status_label = "추가 확인 필요"
        scope_note = str(profile.get("general_scope_note") or "").strip()
        exclusion_note = str(profile.get("conditional_exclusion_summary") or "").strip()
        summary = " ".join(note for note in (scope_note, exclusion_note) if note)

    payload = {
        "status": status,
        "status_label": status_label,
        "summary": summary,
        "authority_note": authority_note,
        "conditions": conditions,
        "clarification_questions": questions,
        "required_evidence": required_evidence,
        "source_evidence": [_source_evidence(chunk) for chunk in direct_chunks],
    }
    return PolicyClauseDecision(
        answer=_join_decision_answer(summary, authority_note, conditions),
        payload=payload,
        chunks=direct_chunks,
    )


def _format_won(value: int) -> str:
    return f"{value:,}원"


def _parse_amount(question: str) -> int | None:
    match = re.search(r"(\d+(?:,\d{3})*)\s*만원", question)
    if match:
        return int(match.group(1).replace(",", "")) * 10000
    match = re.search(r"(\d+(?:,\d{3})*)\s*원", question)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _source_ref(rule: DeductibleRule) -> str:
    page = f" p.{rule.source_page}" if rule.source_page is not None else ""
    chunk = f", chunk={rule.source_chunk_id}" if rule.source_chunk_id else ""
    clause = f", {rule.source_clause}" if rule.source_clause else ""
    return f"{rule.source_doc}{page}{clause}{chunk}"


def _calculate_deductible(amount: int, rule: DeductibleRule) -> int:
    amount_value = Decimal(str(amount))
    ratio_value = amount_value * rule.copay_ratio
    minimum_value = rule.get_min_deductible()
    deductible = max(minimum_value, ratio_value)
    deductible = min(amount_value, deductible)
    return int(deductible.quantize(Decimal("1")))


def build_absent_code_guard_answer(question: str, chunks: list[Chunk]) -> str | None:
    """Return a generic refusal when the user asks to assert an unseen code."""

    if "근거가 없어도" not in question and "답하세요" not in question:
        return None
    codes = [code for code in _CODE_PATTERN.findall(question.upper()) if len(code) >= 4]
    if not codes:
        return None
    combined_sources = "\n".join(chunk.text for chunk in chunks)
    missing_codes = [code for code in dict.fromkeys(codes) if code not in combined_sources.upper()]
    if not missing_codes:
        return None
    code_text = ", ".join(missing_codes)
    return (
        f"요청하신 {code_text} 코드에 대한 근거는 현재 제공된 문서에서 확인되지 않습니다. "
        "문서 근거 없이 없는 코드를 사실처럼 답할 수 없습니다.\n"
        "[출처: 구조화 안전 검증]"
    )


def build_generation_deductible_comparison_answer(question: str) -> str | None:
    """Build 4th/5th generation deductible comparison from the approved rule table."""

    compact = _compact(question)
    if not all(term in compact for term in ("4세대", "5세대", "비중증", "비급여")):
        return None
    amount = _parse_amount(question)
    if amount is None:
        return None
    visit_type = "hospitalization" if "입원" in compact else "outpatient"
    fourth_rule = lookup_rule("4th", "비중증비급여", visit_type)
    fifth_rule = lookup_rule("5th", "비중증비급여", visit_type)
    fourth_deductible = _calculate_deductible(amount, fourth_rule)
    fifth_deductible = _calculate_deductible(amount, fifth_rule)
    return (
        "승인된 공제 규칙표 기준의 비중증 비급여 청구액 비교입니다.\n\n"
        "| 구분 | 공제 기준 | 공제금액 | 예상 지급금액 |\n"
        "| --- | --- | ---: | ---: |\n"
        f"| 4세대 | {fourth_rule.description} | {_format_won(fourth_deductible)} | {_format_won(amount - fourth_deductible)} |\n"
        f"| 5세대 | {fifth_rule.description} | {_format_won(fifth_deductible)} | {_format_won(amount - fifth_deductible)} |\n\n"
        "중증/비중증 구분과 실제 보장 특약 여부는 영수증 및 세부내역서로 최종 확인해야 합니다.\n"
        f"[출처: {_source_ref(fourth_rule)} / {_source_ref(fifth_rule)}]"
    )


def _parse_hira_context_rows(hira_context: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current_source = "심평원"
    for raw_line in hira_context.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        content = line[2:]
        if ":" in content:
            source, content = content.split(":", 1)
            current_source = source.strip()
        for segment in re.split(r"\s*/\s*", content):
            match = _HIRA_CODE_SEGMENT_PATTERN.search(segment.strip())
            if not match:
                continue
            body = match.group("body").strip()
            score_match = _HIRA_SCORE_PATTERN.search(body)
            score = score_match.group("score") if score_match else ""
            if score_match:
                body = (body[: score_match.start()] + body[score_match.end():]).strip(" -:")
            name = body or match.group("code")
            rows.append({
                "code": match.group("code"),
                "name": name,
                "score": score,
                "source": current_source,
            })
    return rows


def build_hira_fee_answer(question: str, hira_context: str | None) -> str | None:
    """Build HIRA fee-code answers only from direct HIRA source rows."""

    if not hira_context:
        return None
    rows = _parse_hira_context_rows(hira_context)
    if not rows:
        return None
    lines = [
        "심평원 수가표 직접 조회 근거에서 확인되는 수가코드는 다음과 같습니다.",
        "",
        "| 수가코드 | 항목 | 점수 | 출처 |",
        "| --- | --- | ---: | --- |",
    ]
    seen: set[str] = set()
    for row in rows:
        key = f"{row['code']}|{row['name']}|{row['score']}"
        if key in seen:
            continue
        seen.add(key)
        score = row["score"] or "원문 행에서 별도 확인 필요"
        lines.append(f"| {row['code']} | {row['name']} | {score} | {row['source']} |")
    if "SOL" in question or "지급비율" in question:
        lines.extend([
            "",
            "SOL 지급비율은 이 심평원 행만으로 확정할 수 없습니다. GraphDB 후보 값은 실무자 승인 전까지 확정 지급 판단에 쓰지 않습니다.",
        ])
    return "\n".join(lines)
