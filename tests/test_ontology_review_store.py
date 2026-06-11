from __future__ import annotations

from pathlib import Path

from src.ontology.review_store import (
    APPLIED,
    APPROVED,
    HELD,
    PENDING,
    OntologyCandidate,
    OntologyReviewStore,
    build_test_candidate,
)


def make_store(tmp_path: Path) -> OntologyReviewStore:
    return OntologyReviewStore(
        candidates_path=tmp_path / "candidates.jsonl",
        review_log_path=tmp_path / "review_log.jsonl",
        applied_reviews_path=tmp_path / "applied_reviews.jsonl",
    )


def test_review_store_decision_logs_status_transition(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_candidate(
        OntologyCandidate(
            candidate_id="cand-1",
            concept_id="cond.new",
            canonical_name="신규 조건",
            aliases=["신규조건"],
        )
    )

    updated = store.decide("cand-1", "hold", reviewer="tester", reason="need evidence")

    assert updated.status == HELD
    assert store.summary()[HELD] == 1
    log_text = (tmp_path / "review_log.jsonl").read_text(encoding="utf-8")
    assert '"decision": "hold"' in log_text
    assert '"reviewer": "tester"' in log_text


def test_review_store_records_structured_hold_feedback(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_candidate(
        OntologyCandidate(
            candidate_id="cand-1",
            concept_id="cond.new",
            canonical_name="신규 조건",
            candidate_aliases=["잘못된 표현"],
        )
    )

    updated = store.decide(
        "cand-1",
        "hold",
        reviewer="tester",
        reason="근거가 다른 문맥입니다.",
        hold_reason_codes=["evidence_mismatch", "alias_mismatch", "unknown"],
    )

    feedback = updated.properties["review_feedback"]
    assert feedback["hold_reason_codes"] == ["evidence_mismatch", "alias_mismatch"]
    assert "원문 근거 연결 부적절" in feedback["hold_reason_labels"]
    assert feedback["note"] == "근거가 다른 문맥입니다."
    log_text = (tmp_path / "review_log.jsonl").read_text(encoding="utf-8")
    assert '"hold_reason_codes": ["evidence_mismatch", "alias_mismatch"]' in log_text


def test_auto_approve_test_candidates_excludes_production_candidates(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_candidate(build_test_candidate("test-cand"))
    store.add_candidate(
        OntologyCandidate(
            candidate_id="prod-cand",
            concept_id="cond.production",
            canonical_name="운영 후보",
            aliases=["운영후보"],
            test_candidate=False,
        )
    )

    selected = store.auto_approve_test_candidates()

    assert [candidate.candidate_id for candidate in selected] == ["test-cand"]
    statuses = {candidate.candidate_id: candidate.status for candidate in store.load_candidates()}
    assert statuses["test-cand"] == APPROVED
    assert statuses["prod-cand"] == PENDING


def test_auto_approve_codex_development_candidates_requires_dev_review_metadata(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_candidate(
        OntologyCandidate(
            candidate_id="dev-cand",
            concept_id="cond.dev",
            canonical_name="개발 검증 후보",
            aliases=["개발검증후보"],
            risk_flags=["dev_auto_approval"],
            source_evidence=[
                {
                    "doc_short": "개발검증",
                    "doc_name": "개발 검증 후보",
                    "page": 1,
                    "chunk_id": "dev-cand",
                    "excerpt": "개발 단계 자동 승인 검증용 후보입니다.",
                    "confidence": 1.0,
                }
            ],
            properties={
                "codex_dev_review": {
                    "decision": "approve",
                    "development_only": True,
                    "domain_fit": True,
                    "evidence_fit": True,
                    "risk_level": "low",
                    "reason": "development-only ontology pipeline validation",
                }
            },
            test_candidate=True,
        )
    )
    store.add_candidate(
        OntologyCandidate(
            candidate_id="unreviewed-cand",
            concept_id="cond.unreviewed",
            canonical_name="검토 누락 후보",
            aliases=["검토누락후보"],
            risk_flags=["dev_auto_approval"],
            source_evidence=[
                {
                    "doc_short": "개발검증",
                    "doc_name": "개발 검증 후보",
                    "page": 2,
                    "chunk_id": "unreviewed-cand",
                    "excerpt": "Codex 개발 검토 metadata가 없는 후보입니다.",
                    "confidence": 1.0,
                }
            ],
        )
    )

    selected = store.auto_approve_codex_development_candidates()

    assert [candidate.candidate_id for candidate in selected] == ["dev-cand"]
    statuses = {candidate.candidate_id: candidate.status for candidate in store.load_candidates()}
    assert statuses["dev-cand"] == APPROVED
    assert statuses["unreviewed-cand"] == PENDING
    log_text = (tmp_path / "review_log.jsonl").read_text(encoding="utf-8")
    assert '"reviewer_type": "codex_dev_auto"' in log_text


def test_auto_approve_codex_development_candidates_requires_test_candidate_flag(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_candidate(
        OntologyCandidate(
            candidate_id="prod-dev-cand",
            concept_id="cond.prod_dev",
            canonical_name="운영 개발 후보",
            aliases=["운영개발후보"],
            risk_flags=["dev_auto_approval"],
            source_evidence=[
                {
                    "doc_short": "개발검증",
                    "doc_name": "개발 검증 후보",
                    "page": 1,
                    "chunk_id": "prod-dev-cand",
                    "excerpt": "개발 자동 승인 metadata는 있으나 test_candidate가 아닙니다.",
                    "confidence": 1.0,
                }
            ],
            properties={
                "codex_dev_review": {
                    "decision": "approve",
                    "development_only": True,
                    "domain_fit": True,
                    "evidence_fit": True,
                    "risk_level": "low",
                    "reason": "development-only ontology pipeline validation",
                }
            },
            test_candidate=False,
        )
    )

    selected = store.auto_approve_codex_development_candidates()

    assert selected == []
    assert store.load_candidates()[0].status == PENDING


def test_mark_approved_as_applied_preserves_applied_candidate_for_manifest(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_candidate(build_test_candidate("test-cand"))
    store.auto_approve_test_candidates()

    applied = store.mark_approved_as_applied(manifest_path=tmp_path / "concepts.active.json")

    assert [candidate.candidate_id for candidate in applied] == ["test-cand"]
    assert store.load_candidates()[0].status == APPLIED
    assert store.approved_or_applied_candidates()[0].candidate_id == "test-cand"
