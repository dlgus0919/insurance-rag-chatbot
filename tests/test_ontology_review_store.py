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


def test_mark_approved_as_applied_preserves_applied_candidate_for_manifest(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_candidate(build_test_candidate("test-cand"))
    store.auto_approve_test_candidates()

    applied = store.mark_approved_as_applied(manifest_path=tmp_path / "concepts.active.json")

    assert [candidate.candidate_id for candidate in applied] == ["test-cand"]
    assert store.load_candidates()[0].status == APPLIED
    assert store.approved_or_applied_candidates()[0].candidate_id == "test-cand"
