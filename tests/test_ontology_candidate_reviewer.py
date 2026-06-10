from __future__ import annotations

from src.ontology.candidate_reviewer import build_codex_dev_review


def test_dev_review_approves_low_risk_evidence_backed_candidate() -> None:
    review = build_codex_dev_review(
        candidate_type="alias_or_expansion",
        source_evidence=[{"excerpt": "교통사고 상해 근거"}],
        similar_expressions=["교통상해"],
        target_terms=["교통사고 상해"],
    )

    assert review["decision"] == "approve"
    assert review["development_only"] is True
    assert review["domain_fit"] is True
    assert review["evidence_fit"] is True
    assert review["risk_level"] == "low"


def test_dev_review_holds_payment_logic_or_unsupported_candidates() -> None:
    review = build_codex_dev_review(
        candidate_type="payment_logic",
        source_evidence=[{"excerpt": "보험금 계산 근거"}],
        similar_expressions=["감액 한도"],
    )

    assert review["decision"] == "hold"
    assert review["risk_level"] == "medium"
    assert "자동 승인 금지" in review["reason"]


def test_dev_review_holds_expression_without_target_overlap() -> None:
    review = build_codex_dev_review(
        candidate_type="alias_or_expansion",
        source_evidence=[{"excerpt": "교통사고 상해 근거"}],
        similar_expressions=["자동차 사고"],
        target_terms=["입원 치료"],
    )

    assert review["decision"] == "hold"
    assert "기존 concept 표현" in review["reason"]


def test_dev_review_holds_scope_condition_terms() -> None:
    review = build_codex_dev_review(
        candidate_type="alias_or_expansion",
        source_evidence=[{"excerpt": "치료목적에 한함"}],
        similar_expressions=["치료목적에 한함"],
        target_terms=["치료 목적"],
    )

    assert review["decision"] == "hold"
    assert "지급/면책/감액/한도" in review["reason"]


def test_dev_review_holds_payment_or_coverage_scope_terms_in_alias_candidate() -> None:
    review = build_codex_dev_review(
        candidate_type="alias_or_expansion",
        source_evidence=[{"excerpt": "보험금 지급여부"}],
        similar_expressions=["보험금 지급여부"],
        target_terms=["실손"],
    )

    assert review["decision"] == "hold"
    assert "지급/면책/감액/한도" in review["reason"]


def test_dev_review_holds_incomplete_or_broad_alias_terms() -> None:
    incomplete = build_codex_dev_review(
        candidate_type="alias_or_expansion",
        source_evidence=[{"excerpt": "진단서를 제출"}],
        similar_expressions=["진단서를"],
        target_terms=["진단서"],
    )
    broad = build_codex_dev_review(
        candidate_type="alias_or_expansion",
        source_evidence=[{"excerpt": "자동차사고"}],
        similar_expressions=["자동차사고"],
        target_terms=["이륜자동차 운전"],
    )

    assert incomplete["decision"] == "hold"
    assert broad["decision"] == "hold"
