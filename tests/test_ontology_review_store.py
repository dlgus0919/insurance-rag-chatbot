from __future__ import annotations

from pathlib import Path

import json

import pytest

from src.ontology.approval_integrity import (
    StaleApprovalPatchError,
    canonical_json_hash,
)
from src.ontology.review_store import (
    APPLIED,
    APPROVED,
    HELD,
    PENDING,
    OntologyCandidate,
    OntologyReviewStore,
    build_test_candidate,
    is_codex_development_auto_approvable,
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
    base_path = tmp_path / "concepts.json"
    base_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "version": "test",
                "concepts": [
                    {"concept_id": "cond.dev", "canonical_name": "개발 검증 조건"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store.add_candidate(
        OntologyCandidate(
            candidate_id="dev-cand",
            concept_id="cond.dev",
            canonical_name="개발 검증 후보",
            aliases=["개발검증후보"],
            evidence_tags=["source:dev-cand"],
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
                "candidate_type": "evidence_tag",
                "target_concept_id": "cond.dev",
                "codex_dev_review": {
                    "decision": "approve",
                    "development_only": True,
                    "domain_fit": True,
                    "evidence_fit": True,
                    "risk_level": "low",
                    "reason": "development-only ontology pipeline validation",
                }
            },
            runtime_properties={"internal_decision": "must-not-auto-approve"},
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

    selected = store.auto_approve_codex_development_candidates(
        base_manifest_path=base_path
    )

    assert [candidate.candidate_id for candidate in selected] == ["dev-cand"]
    statuses = {candidate.candidate_id: candidate.status for candidate in store.load_candidates()}
    assert statuses["dev-cand"] == APPROVED
    assert statuses["unreviewed-cand"] == PENDING
    log_text = (tmp_path / "review_log.jsonl").read_text(encoding="utf-8")
    assert '"reviewer_type": "codex_dev_auto"' in log_text
    review_log = json.loads(log_text)
    operations = review_log["approval_patch"]["allowed_operations"]
    assert [operation["path"] for operation in operations] == [
        f"/concepts/cond.dev/evidence_tags/{canonical_json_hash('source:dev-cand')}"
    ]
    assert all("/properties/" not in operation["path"] for operation in operations)


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


def test_codex_development_auto_approval_rejects_new_concept_scope() -> None:
    candidate = OntologyCandidate(
        candidate_id="dev-new-concept",
        concept_id="cond.new",
        canonical_name="개발 신규 개념",
        evidence_tags=["source:dev-new-concept"],
        risk_flags=["dev_auto_approval"],
        source_evidence=[{"chunk_id": "dev-new-concept", "excerpt": "근거"}],
        properties={
            "candidate_type": "new_concept",
            "codex_dev_review": {
                "decision": "approve",
                "development_only": True,
                "domain_fit": True,
                "evidence_fit": True,
                "risk_level": "low",
            },
        },
        test_candidate=True,
    )

    assert is_codex_development_auto_approvable(candidate) is False


def test_mark_approved_as_applied_preserves_applied_candidate_for_manifest(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_candidate(build_test_candidate("test-cand"))
    store.auto_approve_test_candidates()

    candidate = store.get_candidate("test-cand")
    patch = store.latest_approval_patch(candidate.candidate_id)
    assert patch is not None

    applied = store.mark_approved_as_applied(
        manifest_path=tmp_path / "concepts.active.json",
        approval_patches={candidate.candidate_id: patch},
        active_content_hash="active-hash",
    )

    assert [candidate.candidate_id for candidate in applied] == ["test-cand"]
    assert store.load_candidates()[0].status == APPLIED
    assert store.approved_or_applied_candidates()[0].candidate_id == "test-cand"
    applied_row = json.loads((tmp_path / "applied_reviews.jsonl").read_text(encoding="utf-8"))
    assert applied_row["candidate_payload_hash"] == candidate.approval_payload_hash()
    assert applied_row["approval_patch_hash"] == patch.content_hash()
    assert applied_row["active_content_hash"] == "active-hash"
    assert applied_row["applied_operation_paths"] == [
        operation.path for operation in patch.allowed_operations
    ]


def test_runtime_concept_does_not_promote_candidate_control_properties() -> None:
    candidate = OntologyCandidate(
        candidate_id="cand-control",
        concept_id="cond.alpha",
        canonical_name="조건 A",
        properties={
            "candidate_type": "evidence_tag",
            "review_feedback": {"note": "internal"},
        },
        runtime_properties={"decision_polarity": "review"},
    )

    concept = candidate.runtime_concept()

    assert concept["properties"] == {"decision_polarity": "review"}
    assert "candidate_type" not in concept["properties"]
    assert "review_feedback" not in concept["properties"]


def test_candidate_approval_hash_excludes_lifecycle_state() -> None:
    candidate = OntologyCandidate(
        candidate_id="cand-hash",
        concept_id="cond.alpha",
        canonical_name="조건 A",
        aliases=["조건A"],
        runtime_properties={"decision_polarity": "review"},
    )

    before = candidate.approval_payload_hash()
    candidate.status = APPROVED
    candidate.properties["applied_at"] = "2026-07-18T00:00:00Z"

    assert candidate.approval_payload_hash() == before


def test_candidate_runtime_properties_round_trip(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_candidate(
        OntologyCandidate(
            candidate_id="cand-runtime",
            concept_id="cond.runtime",
            canonical_name="런타임 개념",
            runtime_properties={"source_grounded_decision": "review"},
        )
    )

    assert store.load_candidates()[0].runtime_properties == {
        "source_grounded_decision": "review"
    }


def test_approve_requires_only_explicit_projected_paths(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    base_path = tmp_path / "concepts.json"
    base_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "version": "test",
                "concepts": [
                    {"concept_id": "cond.alpha", "canonical_name": "조건 A"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    candidate = OntologyCandidate(
        candidate_id="cand-evidence",
        concept_id="cond.alpha",
        canonical_name="조건 A",
        evidence_tags=["source:alpha"],
        candidate_aliases=["승인 밖 표현"],
        properties={"candidate_type": "evidence_tag", "target_concept_id": "cond.alpha"},
        source_evidence=[{"chunk_id": "chunk:1", "excerpt": "근거"}],
    )
    store.add_candidate(candidate)
    approved_path = (
        f"/concepts/cond.alpha/evidence_tags/{canonical_json_hash('source:alpha')}"
    )

    with pytest.raises(ValueError, match="approved_paths"):
        store.decide("cand-evidence", "approve", base_manifest_path=base_path)

    with pytest.raises(ValueError, match="not available"):
        store.decide(
            "cand-evidence",
            "approve",
            approved_paths=["/concepts/cond.alpha/candidate_aliases/not-exposed"],
            base_manifest_path=base_path,
        )

    updated = store.decide(
        "cand-evidence",
        "approve",
        reviewer="tester",
        approved_paths=[approved_path],
        base_manifest_path=base_path,
    )

    assert updated.status == APPROVED
    review_row = json.loads((tmp_path / "review_log.jsonl").read_text(encoding="utf-8"))
    assert review_row["candidate_payload_hash"] == updated.approval_payload_hash()
    assert review_row["approval_patch"]["allowed_operations"][0]["path"] == approved_path


def test_latest_approval_patch_rejects_stale_candidate_payload(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    base_path = tmp_path / "concepts.json"
    base_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "version": "test",
                "concepts": [
                    {"concept_id": "cond.alpha", "canonical_name": "조건 A"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    candidate = OntologyCandidate(
        candidate_id="cand-stale",
        concept_id="cond.alpha",
        canonical_name="조건 A",
        evidence_tags=["source:alpha"],
        properties={"candidate_type": "evidence_tag", "target_concept_id": "cond.alpha"},
        source_evidence=[{"chunk_id": "chunk:1", "excerpt": "근거"}],
    )
    store.add_candidate(candidate)
    approved_path = f"/concepts/cond.alpha/evidence_tags/{canonical_json_hash('source:alpha')}"
    store.decide(
        candidate.candidate_id,
        "approve",
        approved_paths=[approved_path],
        base_manifest_path=base_path,
    )

    changed = store.get_candidate(candidate.candidate_id)
    changed.evidence_tags.append("source:changed")
    store.add_candidate(changed, replace=True)

    with pytest.raises(StaleApprovalPatchError, match="stale"):
        store.latest_approval_patch(candidate.candidate_id)
