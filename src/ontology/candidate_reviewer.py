from __future__ import annotations

from typing import Any


LOW_RISK_CANDIDATE_TYPES = {
    "alias_or_expansion",
    "evidence_tag",
    "search_query_expansion",
}
PROHIBITED_AUTO_APPROVAL_TYPES = {
    "exclusion_rule",
    "payment_logic",
    "deductible_rule",
    "benefit_limit",
    "coordination_rule",
    "coverage_decision_edge",
}
PROHIBITED_RISK_TERMS = {
    "면책",
    "부지급",
    "감액",
    "공제",
    "한도",
    "지급 제외",
    "보험금",
    "보험",
    "담보",
    "지급",
    "보상",
    "보상하지",
    "보장",
    "급여",
    "비급여",
    "제외",
    "포함",
    "한함",
    "조건",
    "대상",
    "특약",
    "가입",
    "계약",
    "피보험",
    "한정",
    "위반",
    "청구권",
    "간주",
    "자동차",
}
UNSAFE_AUTO_APPROVAL_FRAGMENTS = {
    "상대가치",
    "분류번호",
    "요양급여",
    "의료급여",
    "질병군",
    "진단적",
    "검사결과",
    "목록표",
    "일반원칙",
    "위한",
}


def contains_prohibited_risk_term(values: list[str]) -> bool:
    joined = " ".join(values)
    return any(term in joined for term in PROHIBITED_RISK_TERMS)


def is_safe_development_expression(expression: str) -> bool:
    text = " ".join(str(expression or "").split())
    if len(text) < 3 or len(text) > 18:
        return False
    if any(fragment in text for fragment in UNSAFE_AUTO_APPROVAL_FRAGMENTS):
        return False
    if any(char.isdigit() for char in text):
        return False
    if any("A" <= char <= "Z" or "a" <= char <= "z" for char in text):
        return False
    if text.startswith(("및 ", "또는 ", "은 ", "는 ", "을 ", "를 ", "에 ", "에서 ")):
        return False
    if text.endswith(("을", "를", "은", "는", "이", "가", "에", "로", "으로", "와", "과")):
        return False
    if len(text.split()) > 3:
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
) -> dict[str, Any]:
    has_evidence = bool(source_evidence)
    low_risk_type = candidate_type in LOW_RISK_CANDIDATE_TYPES
    prohibited_type = candidate_type in PROHIBITED_AUTO_APPROVAL_TYPES
    prohibited_term = contains_prohibited_risk_term(similar_expressions)
    safe_expressions = bool(similar_expressions) and all(is_safe_development_expression(item) for item in similar_expressions)
    target_overlap = True
    if target_terms:
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
        }

    reasons: list[str] = []
    if not has_evidence:
        reasons.append("source_evidence 없음")
    if not low_risk_type:
        reasons.append(f"저위험 후보 타입 아님: {candidate_type}")
    if prohibited_type:
        reasons.append(f"자동 승인 금지 후보 타입: {candidate_type}")
    if prohibited_term:
        reasons.append("지급/면책/감액/한도 관련 표현 포함")
    if not safe_expressions:
        reasons.append("개발 자동 승인에 안전한 표현 형태가 아님")
    if not target_overlap:
        reasons.append("기존 concept 표현과 충분한 형태적 연결성이 없음")
    if conflict_detected:
        reasons.append("기존 ontology 표현과 충돌 가능")

    return {
        "decision": "hold",
        "development_only": True,
        "domain_fit": not prohibited_type,
        "evidence_fit": has_evidence,
        "risk_level": "medium" if has_evidence else "high",
        "reason": "; ".join(reasons) or "개발 자동 승인 조건을 충족하지 않습니다.",
    }
