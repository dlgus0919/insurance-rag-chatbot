from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from src.graph.normalizer import normalize_name
from src.ontology.candidate_quality import analyze_candidate_quality
from src.ontology.review_store import APPLIED, APPROVED, HELD, REJECTED, OntologyCandidate


VALID_DECISIONS = {"approve", "hold", "reject"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
ALLOWED_REASON_CODES = {
    "safe_alias",
    "sentence_fragment",
    "too_broad",
    "alias_mismatch",
    "evidence_mismatch",
    "ownership_conflict",
    "policy_risk",
    "needs_more_evidence",
    "schema_uncertain",
}
UNSAFE_APPROVAL_REASON_CODES = {
    "sentence_fragment",
    "too_broad",
    "alias_mismatch",
    "evidence_mismatch",
    "ownership_conflict",
    "policy_risk",
    "needs_more_evidence",
    "schema_uncertain",
}
REASON_CODE_ALIASES = {
    "risk_term_guardrail": "policy_risk",
    "payment_rule_risk": "policy_risk",
    "payment_risk": "policy_risk",
    "rule_risk": "policy_risk",
    "fragment": "sentence_fragment",
    "sentence_like_fragment": "sentence_fragment",
    "broad_term": "too_broad",
    "conflict": "ownership_conflict",
}

SYSTEM_PROMPT = """\
당신은 보험 도메인 온톨로지 후보 검토 보조자입니다.
후보 alias는 검색 보강 표현인지 판단할 뿐이며 보험금 지급, 면책, 감액, 한도 계산 rule을 만들면 안 됩니다.
target concept과 다른 개념이면 approve하지 마세요.
원문 evidence가 target concept과 어긋나면 hold 또는 reject로 판단하세요.
문장 조각, 조사로 끝나는 표현, 접속 표현은 reject 또는 suggested_rewrite를 제안하세요.
반드시 JSON 객체만 출력하세요.
"""


class EnrichmentClient(Protocol):
    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.0,
        num_ctx: int | None = None,
        reasoning_mode: str = "off",
    ) -> str:
        ...


@dataclass(frozen=True)
class EnrichmentParseResult:
    payload: dict[str, Any]
    validation_errors: list[str] = field(default_factory=list)
    raw_text: str = ""
    json_valid: bool = True
    schema_valid: bool = True


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _string_list(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text and text not in result:
            result.append(text)
        if limit is not None and len(result) >= limit:
            break
    return result


def _limited_evidence(source_evidence: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in source_evidence[:limit]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "doc_short": _clean_text(item.get("doc_short") or item.get("doc_name")),
                "page": _clean_text(item.get("page")),
                "excerpt": _clean_text(item.get("excerpt"))[:700],
            }
        )
    return rows


def _known_conflicts(candidate: OntologyCandidate, all_candidates: Iterable[OntologyCandidate]) -> list[dict[str, str]]:
    owner_map: dict[str, list[OntologyCandidate]] = {}
    for item in all_candidates:
        for alias in item.candidate_aliases:
            normalized = normalize_name(alias)
            if normalized:
                owner_map.setdefault(normalized, []).append(item)

    conflicts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for alias in candidate.candidate_aliases:
        normalized = normalize_name(alias)
        if not normalized:
            continue
        for owner in owner_map.get(normalized, []):
            if owner.concept_id == candidate.concept_id:
                continue
            key = (alias, owner.concept_id)
            if key in seen:
                continue
            conflicts.append(
                {
                    "expression": alias,
                    "other_candidate_id": owner.candidate_id,
                    "other_concept_id": owner.concept_id,
                    "other_canonical_name": owner.canonical_name,
                }
            )
            seen.add(key)
    return conflicts


def build_enrichment_input(
    candidate: OntologyCandidate,
    *,
    all_candidates: Iterable[OntologyCandidate] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the minimal structured input given to a local ontology enrichment LLM."""

    all_candidate_list = list(all_candidates or [])
    display = candidate.properties.get("display") if isinstance(candidate.properties.get("display"), dict) else {}
    return {
        "candidate_id": candidate.candidate_id,
        "candidate_type": _clean_text(candidate.properties.get("candidate_type")) or "alias_or_expansion",
        "target": {
            "concept_id": candidate.concept_id,
            "canonical_name": candidate.canonical_name,
            "node_type": candidate.node_type,
            "known_aliases": candidate.aliases,
        },
        "candidate_aliases": candidate.candidate_aliases,
        "display_summary": _clean_text(display.get("summary")),
        "source_evidence": _limited_evidence(candidate.source_evidence),
        "known_conflicts": _known_conflicts(candidate, all_candidate_list),
        "quality_warnings": [issue.to_dict() for issue in analyze_candidate_quality(candidate, all_candidates=all_candidate_list)],
        "existing_review": candidate.properties.get("codex_dev_review") if isinstance(candidate.properties.get("codex_dev_review"), dict) else {},
        "status": candidate.status,
        "review_policy_summary": policy
        or {
            "reject_sentence_fragments": True,
            "reject_payment_rule_changes": True,
            "reject_broad_terms": True,
        },
    }


def build_enrichment_prompt(payload: dict[str, Any]) -> str:
    allowed_reason_codes = ", ".join(sorted(ALLOWED_REASON_CODES))
    return (
        "다음 온톨로지 후보를 평가하고 지정 schema의 JSON만 반환하세요.\n\n"
        "reason_codes는 반드시 다음 값 중에서만 고르세요:\n"
        f"{allowed_reason_codes}\n\n"
        "출력 schema:\n"
        "{\n"
        '  "schema_version": 1,\n'
        '  "overall_decision": "approve|hold|reject",\n'
        '  "domain_fit": true,\n'
        '  "evidence_fit": true,\n'
        '  "risk_level": "low|medium|high",\n'
        '  "confidence": 0.0,\n'
        '  "alias_assessments": [\n'
        '    {"expression": "...", "decision": "approve|hold|reject", "reason_codes": ["safe_alias"], "reason": "...", "suggested_rewrite": ""}\n'
        "  ],\n"
        '  "refined_aliases": [],\n'
        '  "practitioner_summary": "...",\n'
        '  "example_questions": ["..."],\n'
        '  "review_notes": "..."\n'
        "}\n\n"
        f"입력 payload:\n{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}"
    )


def fallback_enrichment(reason: str = "schema_uncertain") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "overall_decision": "hold",
        "domain_fit": False,
        "evidence_fit": False,
        "risk_level": "high",
        "confidence": 0.0,
        "alias_assessments": [
            {
                "expression": "",
                "decision": "hold",
                "reason_codes": ["schema_uncertain"],
                "reason": reason,
                "suggested_rewrite": "",
            }
        ],
        "refined_aliases": [],
        "practitioner_summary": "LLM 출력이 안정적인 schema를 통과하지 못해 보류로 처리합니다.",
        "example_questions": [],
        "review_notes": reason,
    }


def _extract_json_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        first = stripped.find("{")
        last = stripped.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return None, "json_parse_failed"
        try:
            value = json.loads(stripped[first : last + 1])
        except json.JSONDecodeError:
            return None, "json_parse_failed"
    if not isinstance(value, dict):
        return None, "json_not_object"
    return value, None


def _normalize_alias_assessments(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(value, list):
        return [], ["alias_assessments_not_list"]
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"alias_assessments[{index}]_not_object")
            continue
        decision = str(item.get("decision") or "hold").strip()
        if decision not in VALID_DECISIONS:
            errors.append(f"alias_assessments[{index}]_invalid_decision")
            decision = "hold"
        raw_reason_codes = _string_list(item.get("reason_codes"), limit=6)
        reason_codes = [REASON_CODE_ALIASES.get(code, code) for code in raw_reason_codes]
        unknown_codes = [code for code in reason_codes if code not in ALLOWED_REASON_CODES]
        if unknown_codes:
            errors.append(f"alias_assessments[{index}]_unknown_reason_codes:{','.join(unknown_codes)}")
            reason_codes = [code for code in reason_codes if code in ALLOWED_REASON_CODES]
        result.append(
            {
                "expression": _clean_text(item.get("expression")),
                "decision": decision,
                "reason_codes": reason_codes or ["schema_uncertain"],
                "reason": _clean_text(item.get("reason")),
                "suggested_rewrite": _clean_text(item.get("suggested_rewrite")),
            }
        )
    return result, errors


def validate_enrichment_output(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate and normalize the LLM JSON output schema."""

    errors: list[str] = []
    decision = str(payload.get("overall_decision") or "").strip()
    if decision not in VALID_DECISIONS:
        errors.append("invalid_overall_decision")
        decision = "hold"
    risk_level = str(payload.get("risk_level") or "").strip()
    if risk_level not in VALID_RISK_LEVELS:
        errors.append("invalid_risk_level")
        risk_level = "high"

    domain_fit = payload.get("domain_fit")
    evidence_fit = payload.get("evidence_fit")
    if not isinstance(domain_fit, bool):
        errors.append("domain_fit_not_bool")
        domain_fit = False
    if not isinstance(evidence_fit, bool):
        errors.append("evidence_fit_not_bool")
        evidence_fit = False

    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        errors.append("confidence_not_number")
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))

    alias_assessments, alias_errors = _normalize_alias_assessments(payload.get("alias_assessments"))
    errors.extend(alias_errors)

    normalized = {
        "schema_version": 1,
        "overall_decision": decision,
        "domain_fit": domain_fit,
        "evidence_fit": evidence_fit,
        "risk_level": risk_level,
        "confidence": confidence,
        "alias_assessments": alias_assessments,
        "refined_aliases": _string_list(payload.get("refined_aliases"), limit=12),
        "practitioner_summary": _clean_text(payload.get("practitioner_summary")),
        "example_questions": _string_list(payload.get("example_questions"), limit=5),
        "review_notes": _clean_text(payload.get("review_notes")),
    }
    return normalized, errors


def parse_enrichment_response(text: str) -> EnrichmentParseResult:
    payload, json_error = _extract_json_object(text)
    if json_error or payload is None:
        reason = json_error or "json_parse_failed"
        return EnrichmentParseResult(
            payload=fallback_enrichment(reason),
            validation_errors=[reason],
            raw_text=text,
            json_valid=False,
            schema_valid=False,
        )
    normalized, errors = validate_enrichment_output(payload)
    if errors:
        return EnrichmentParseResult(
            payload=fallback_enrichment("; ".join(errors)),
            validation_errors=errors,
            raw_text=text,
            json_valid=True,
            schema_valid=False,
        )
    return EnrichmentParseResult(payload=normalized, validation_errors=[], raw_text=text, json_valid=True, schema_valid=True)


def template_enrichment(candidate: OntologyCandidate, *, all_candidates: Iterable[OntologyCandidate] | None = None) -> dict[str, Any]:
    """Generate deterministic dry-run enrichment for script validation and tests."""

    all_candidate_list = list(all_candidates or [])
    issues = analyze_candidate_quality(candidate, all_candidates=all_candidate_list)
    issue_codes = {issue.code for issue in issues}
    reason_codes: list[str] = []
    if "sentence_fragment_alias" in issue_codes:
        reason_codes.append("sentence_fragment")
    if "candidate_alias_multi_owner" in issue_codes:
        reason_codes.append("ownership_conflict")
    if not candidate.source_evidence:
        reason_codes.append("needs_more_evidence")

    existing = candidate.properties.get("codex_dev_review") if isinstance(candidate.properties.get("codex_dev_review"), dict) else {}
    existing_decision = str(existing.get("decision") or "").strip()
    if existing_decision == "approve" and not reason_codes:
        decision = "approve"
        risk_level = "low"
        domain_fit = True
        evidence_fit = True
        reason_codes = ["safe_alias"]
    else:
        decision = "hold" if reason_codes else "hold"
        risk_level = "high" if {"ownership_conflict", "needs_more_evidence"} & set(reason_codes) else "medium"
        domain_fit = "ownership_conflict" not in reason_codes
        evidence_fit = bool(candidate.source_evidence)
        if not reason_codes:
            reason_codes = ["needs_more_evidence"] if not candidate.source_evidence else ["schema_uncertain"]

    alias_assessments = []
    for alias in candidate.candidate_aliases:
        alias_reason_codes = list(reason_codes)
        alias_decision = "approve" if decision == "approve" else "hold"
        if "sentence_fragment_alias" in {issue.code for issue in issues if issue.term == alias}:
            alias_decision = "reject"
            alias_reason_codes = ["sentence_fragment"]
        alias_assessments.append(
            {
                "expression": alias,
                "decision": alias_decision,
                "reason_codes": alias_reason_codes,
                "reason": "dry-run template judgement",
                "suggested_rewrite": "",
            }
        )

    display = candidate.properties.get("display") if isinstance(candidate.properties.get("display"), dict) else {}
    summary = _clean_text(display.get("summary")) or f"{candidate.canonical_name} 후보 표현 검토가 필요합니다."
    questions = _string_list(display.get("example_questions"), limit=3)
    if not questions:
        questions = [f"{candidate.canonical_name} 관련 약관 근거를 찾아줘"]
    return {
        "schema_version": 1,
        "overall_decision": decision,
        "domain_fit": domain_fit,
        "evidence_fit": evidence_fit,
        "risk_level": risk_level,
        "confidence": 0.5,
        "alias_assessments": alias_assessments,
        "refined_aliases": [] if decision != "approve" else candidate.candidate_aliases,
        "practitioner_summary": summary,
        "example_questions": questions,
        "review_notes": "dry-run template output; no LLM call was made",
    }


def enrich_candidate_with_llm(
    candidate: OntologyCandidate,
    client: EnrichmentClient,
    *,
    all_candidates: Iterable[OntologyCandidate] | None = None,
    policy: dict[str, Any] | None = None,
    temperature: float = 0.0,
) -> EnrichmentParseResult:
    payload = build_enrichment_input(candidate, all_candidates=all_candidates, policy=policy)
    prompt = build_enrichment_prompt(payload)
    raw = client.generate(prompt, system=SYSTEM_PROMPT, temperature=temperature, reasoning_mode="off")
    return parse_enrichment_response(raw)


def enrichment_reason_codes(payload: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for item in payload.get("alias_assessments", []):
        if isinstance(item, dict):
            codes.update(_string_list(item.get("reason_codes")))
    return codes


def is_unsafe_approval(candidate: OntologyCandidate, payload: dict[str, Any]) -> bool:
    if payload.get("overall_decision") != "approve":
        return False
    if payload.get("risk_level") != "low":
        return True
    if payload.get("domain_fit") is not True or payload.get("evidence_fit") is not True:
        return True
    if enrichment_reason_codes(payload).intersection(UNSAFE_APPROVAL_REASON_CODES):
        return True
    issues = analyze_candidate_quality(candidate)
    return bool(issues)


def summarize_enrichment_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_model.setdefault(str(row.get("model") or ""), []).append(row)

    summaries: dict[str, Any] = {}
    for model, model_rows in by_model.items():
        total = len(model_rows)
        decisions = Counter(str(row.get("overall_decision") or "") for row in model_rows)
        unsafe = sum(1 for row in model_rows if row.get("unsafe_approval") is True)
        json_valid = sum(1 for row in model_rows if row.get("json_valid") is True)
        schema_valid = sum(1 for row in model_rows if row.get("schema_valid") is True)
        held_as_approve = sum(1 for row in model_rows if row.get("candidate_status") == HELD and row.get("overall_decision") == "approve")
        rejected_as_approve = sum(1 for row in model_rows if row.get("candidate_status") == REJECTED and row.get("overall_decision") == "approve")
        applied_as_reject = sum(
            1 for row in model_rows if row.get("candidate_status") in {APPROVED, APPLIED} and row.get("overall_decision") == "reject"
        )
        expected_rows = [row for row in model_rows if row.get("has_expected_enrichment") is True]
        expected_pass = sum(1 for row in expected_rows if row.get("expected_checks_ok") is True)
        summaries[model] = {
            "total": total,
            "decision_counts": dict(sorted(decisions.items())),
            "json_validity": json_valid / total if total else 0.0,
            "schema_validity": schema_valid / total if total else 0.0,
            "unsafe_approval_count": unsafe,
            "held_as_approve": held_as_approve,
            "rejected_as_approve": rejected_as_approve,
            "applied_as_reject": applied_as_reject,
            "expected_total": len(expected_rows),
            "expected_pass": expected_pass,
            "expected_pass_rate": expected_pass / len(expected_rows) if expected_rows else 0.0,
        }
    return summaries
