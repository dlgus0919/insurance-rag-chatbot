from __future__ import annotations

from scripts.extract_claim_rule_candidates import extract_candidates_from_text


def test_extracts_ratio_candidate_when_scope_and_source_exist() -> None:
    candidates = extract_candidates_from_text(
        text="5세대 실손의료보험 급여 통원 의료비는 본인부담금의 80%를 보상합니다.",
        doc_short="신한EZ 약관",
        chunk_id="chunk_001",
        page=12,
        article="보상하는 사항",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == "pending"
    assert candidate["proposed_rule"]["category"] == "급여"
    assert candidate["proposed_rule"]["copay_ratio"] == "0.2"
    assert candidate["proposed_links"]["source_refs"] == ["policy_chunk:chunk_001"]
    assert candidate["source_refs"][0]["chunk_id"] == "chunk_001"
    assert candidate["risk_flags"] == []


def test_does_not_extract_number_without_rule_scope() -> None:
    candidates = extract_candidates_from_text(
        text="이 상품의 보험기간은 1년입니다.",
        doc_short="신한EZ 약관",
        chunk_id="chunk_002",
        page=13,
        article="보험기간",
    )

    assert candidates == []
