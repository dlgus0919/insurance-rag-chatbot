from __future__ import annotations

from typing import Any

from src.ontology.policy import OntologyReviewPolicy, load_review_policy


def contains_prohibited_risk_term(values: list[str], policy: OntologyReviewPolicy | None = None) -> bool:
    review_policy = policy or load_review_policy()
    joined = " ".join(values)
    return any(term in joined for term in review_policy.prohibited_risk_terms)


def is_safe_development_expression(expression: str, policy: OntologyReviewPolicy | None = None) -> bool:
    review_policy = policy or load_review_policy()
    shape = review_policy.expression_shape
    text = " ".join(str(expression or "").split())
    if len(text) < shape.min_length or len(text) > shape.max_length:
        return False
    if any(fragment in text for fragment in review_policy.unsafe_auto_approval_fragments):
        return False
    if not shape.allow_digits and any(char.isdigit() for char in text):
        return False
    if not shape.allow_ascii_letters and any("A" <= char <= "Z" or "a" <= char <= "z" for char in text):
        return False
    if shape.blocked_prefixes and text.startswith(shape.blocked_prefixes):
        return False
    if shape.blocked_suffixes and text.endswith(shape.blocked_suffixes):
        return False
    if len(text.split()) > shape.max_terms:
        return False
    return True


def has_target_overlap(expression: str, target_terms: list[str]) -> bool:
    expr_grams = _bigrams(expression)
    if not expr_grams:
        return False
    for target in target_terms:
        target_grams = _bigrams(target)
        if expr_grams.intersection(target_grams):
            return True
    return False


def _bigrams(value: str) -> set[str]:
    compact = "".join(str(value or "").split()).lower()
    if len(compact) < 2:
        return set()
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def build_codex_dev_review(
    *,
    candidate_type: str,
    source_evidence: list[dict[str, Any]],
    similar_expressions: list[str],
    target_terms: list[str] | None = None,
    conflict_detected: bool = False,
    policy: OntologyReviewPolicy | None = None,
) -> dict[str, Any]:
    review_policy = policy or load_review_policy()
    has_evidence = bool(source_evidence)
    low_risk_type = candidate_type in review_policy.low_risk_candidate_types
    prohibited_type = candidate_type in review_policy.prohibited_auto_approval_types
    prohibited_term = contains_prohibited_risk_term(similar_expressions, review_policy)
    safe_expressions = bool(similar_expressions) and all(
        is_safe_development_expression(item, review_policy) for item in similar_expressions
    )
    target_overlap = True
    if review_policy.auto_approval.require_target_overlap and target_terms:
        target_overlap = all(has_target_overlap(item, target_terms) for item in similar_expressions)
    approvable = (
        has_evidence
        and low_risk_type
        and safe_expressions
        and target_overlap
        and not prohibited_type
        and not prohibited_term
        and not conflict_detected
    )

    if approvable:
        return {
            "decision": "approve",
            "development_only": True,
            "domain_fit": True,
            "evidence_fit": True,
            "risk_level": "low",
            "reason": "개발 단계 검증용 저위험 온톨로지 보강 후보이며 지급/면책/감액/계산 rule을 변경하지 않습니다.",
            "reason_codes": ["low_risk_evidence_backed"],
            "policy_id": review_policy.policy_id,
            "policy_version": review_policy.version,
        }

    reasons: list[str] = []
    reason_codes: list[str] = []
    if not has_evidence:
        reasons.append("source_evidence 없음")
        reason_codes.append("source_evidence_missing")
    if not low_risk_type:
        reasons.append(f"저위험 후보 타입 아님: {candidate_type}")
        reason_codes.append("candidate_type_not_low_risk")
    if prohibited_type:
        reasons.append(f"자동 승인 금지 후보 타입: {candidate_type}")
        reason_codes.append("prohibited_candidate_type")
    if prohibited_term:
        reasons.append("지급/면책/감액/한도 관련 표현 포함")
        reason_codes.append("risk_term_guardrail")
    if not safe_expressions:
        reasons.append("개발 자동 승인에 안전한 표현 형태가 아님")
        reason_codes.append("expression_safety_guardrail")
    if not target_overlap:
        reasons.append("기존 concept 표현과 충분한 형태적 연결성이 없음")
        reason_codes.append("target_overlap_missing")
    if conflict_detected:
        reasons.append("기존 ontology 표현과 충돌 가능")
        reason_codes.append("ontology_conflict")

    return {
        "decision": "hold",
        "development_only": True,
        "domain_fit": not prohibited_type,
        "evidence_fit": has_evidence,
        "risk_level": "medium" if has_evidence else "high",
        "reason": "; ".join(reasons) or "개발 자동 승인 조건을 충족하지 않습니다.",
        "reason_codes": reason_codes or ["auto_approval_condition_failed"],
        "policy_id": review_policy.policy_id,
        "policy_version": review_policy.version,
    }
