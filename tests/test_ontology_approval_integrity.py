from __future__ import annotations

import pytest

from src.ontology.approval_integrity import (
    ApprovalPatch,
    BaseManifestLock,
    audit_active_manifest,
    build_trusted_base_projection,
    canonical_json_hash,
    manifest_content_hash,
    project_candidate_operations,
)
from src.ontology.review_store import OntologyCandidate


def _manifest(*concept_ids: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "version": "base",
        "description": "test manifest",
        "concepts": [
            {
                "concept_id": concept_id,
                "canonical_name": f"개념 {concept_id}",
            }
            for concept_id in concept_ids
        ],
    }


def _provenance(
    active: dict[str, object],
    lock: BaseManifestLock,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-07-18T00:00:00+00:00",
        "base_lock": lock.to_dict(),
        "trusted_base_content_hash": lock.manifest_content_hash,
        "active_content_hash": manifest_content_hash(active),
        "quarantined_concept_ids": [],
        "integrity_issues": [],
        "applied_operations": [],
    }


def test_manifest_content_hash_ignores_only_generated_active_version() -> None:
    first = _manifest("cond.alpha")
    first["version"] = "base+approved-2026-07-18T01:00:00Z"
    second = dict(first)
    second["version"] = "base+approved-2026-07-18T02:00:00Z"

    assert manifest_content_hash(first) == manifest_content_hash(second)

    second["concepts"] = [
        {"concept_id": "cond.alpha", "canonical_name": "다른 개념"}
    ]
    assert manifest_content_hash(first) != manifest_content_hash(second)


def test_manifest_content_hash_preserves_every_non_generated_top_level_field() -> None:
    first = _manifest("cond.alpha")
    second = dict(first)
    second["future_extension"] = {"enabled": True}

    assert manifest_content_hash(first) != manifest_content_hash(second)

    second = dict(first)
    second["description"] = "updated declaration"
    assert manifest_content_hash(first) != manifest_content_hash(second)


def test_trusted_base_projection_quarantines_only_hash_mismatched_concepts() -> None:
    locked_manifest = _manifest("cond.alpha")
    lock = BaseManifestLock.from_manifest(
        locked_manifest,
        source_commit="trusted",
        review_record_id="review-record",
    )
    current = _manifest("cond.alpha", "cond.injected")

    projection, report = build_trusted_base_projection(current, lock)

    assert [row["concept_id"] for row in projection["concepts"]] == ["cond.alpha"]
    assert report.quarantined_concept_ids == ("cond.injected",)


@pytest.mark.parametrize(
    ("field", "replacement", "match"),
    [
        ("schema_version", 0, "schema_version"),
        ("manifest_content_hash", "", "manifest_content_hash"),
        ("source_commit", "", "source_commit"),
        ("review_record_id", "", "review_record_id"),
    ],
)
def test_base_manifest_lock_rejects_unsupported_or_unaccountable_metadata(
    field: str,
    replacement: object,
    match: str,
) -> None:
    payload = BaseManifestLock.from_manifest(
        _manifest("cond.alpha"),
        source_commit="trusted",
        review_record_id="review-record",
    ).to_dict()
    payload[field] = replacement

    with pytest.raises(ValueError, match=match):
        BaseManifestLock.from_dict(payload)


@pytest.mark.parametrize(
    "concept_hashes",
    [
        {"cond.alpha": "valid-hash", "": "another-hash"},
        {"cond.alpha": "valid-hash", "cond.empty": ""},
        {"cond.alpha": "valid-hash", 7: "another-hash"},
        {"cond.alpha": "valid-hash", "cond.nonstring": 7},
    ],
)
def test_base_manifest_lock_rejects_any_malformed_concept_hash_row(
    concept_hashes: dict[object, object],
) -> None:
    payload = BaseManifestLock.from_manifest(
        _manifest("cond.alpha"),
        source_commit="trusted",
        review_record_id="review-record",
    ).to_dict()
    payload["concept_hashes"] = concept_hashes

    with pytest.raises(ValueError, match="concept_hashes"):
        BaseManifestLock.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("description", "changed manifest description"),
        ("schema_version", "2.0"),
    ],
)
def test_trusted_base_projection_rejects_top_level_manifest_drift(
    field: str,
    replacement: str,
) -> None:
    locked_manifest = _manifest("cond.alpha")
    lock = BaseManifestLock.from_manifest(
        locked_manifest,
        source_commit="trusted",
        review_record_id="review-record",
    )
    current = {**locked_manifest, field: replacement}

    projection, report = build_trusted_base_projection(current, lock)

    assert [row["concept_id"] for row in projection["concepts"]] == ["cond.alpha"]
    assert report.state == "stale"
    assert report.issue_counts() == {"BASE_MANIFEST_HASH_MISMATCH": 1}
    assert report.manifest_content_hash != lock.manifest_content_hash


@pytest.mark.parametrize(
    "current",
    [
        {**_manifest("cond.alpha"), "rogue_top_level": True},
        {
            key: value
            for key, value in _manifest("cond.alpha").items()
            if key != "version"
        },
        {
            **_manifest("cond.alpha"),
            "concepts": [{"concept_id": "cond.alpha"}],
        },
    ],
)
def test_trusted_base_projection_rejects_manifest_schema_violations(
    current: dict[str, object],
) -> None:
    locked_manifest = _manifest("cond.alpha")
    lock = BaseManifestLock.from_manifest(
        locked_manifest,
        source_commit="trusted",
        review_record_id="review-record",
    )

    with pytest.raises(ValueError, match="ontology manifest schema validation failed"):
        build_trusted_base_projection(current, lock)


def test_active_manifest_audit_rejects_internally_consistent_top_level_base_drift() -> None:
    locked_manifest = _manifest("cond.alpha")
    lock = BaseManifestLock.from_manifest(
        locked_manifest,
        source_commit="trusted",
        review_record_id="review-record",
    )
    drifted_base = {**locked_manifest, "description": "changed manifest description"}
    active = {**drifted_base, "version": "active"}
    provenance = _provenance(active, lock)

    audit = audit_active_manifest(drifted_base, lock, active, provenance)

    assert audit.report.state == "stale"
    assert audit.report.issue_counts()["BASE_MANIFEST_HASH_MISMATCH"] == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("description", "unapproved active description"),
        ("schema_version", "2.0"),
    ],
)
def test_active_manifest_audit_rejects_top_level_drift_with_recomputed_provenance_hash(
    field: str,
    replacement: str,
) -> None:
    base = _manifest("cond.alpha")
    lock = BaseManifestLock.from_manifest(
        base,
        source_commit="trusted",
        review_record_id="review-record",
    )
    active = {**base, "version": "active", field: replacement}
    provenance = _provenance(active, lock)

    audit = audit_active_manifest(base, lock, active, provenance)

    assert audit.report.state == "stale"
    assert audit.report.issue_counts() == {
        "UNAPPROVED_ACTIVE_MANIFEST_METADATA_DELTA": 1
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.__setitem__("schema_version", 0),
        lambda payload: payload.pop("generated_at"),
        lambda payload: payload.__setitem__("rogue_top_level", True),
        lambda payload: payload.__setitem__("applied_operations", ["not-an-operation"]),
    ],
)
def test_active_manifest_audit_rejects_invalid_provenance_schema(
    mutate,
) -> None:
    base = _manifest("cond.alpha")
    lock = BaseManifestLock.from_manifest(
        base,
        source_commit="trusted",
        review_record_id="review-record",
    )
    active = {**base, "version": "active"}
    provenance = _provenance(active, lock)
    mutate(provenance)

    with pytest.raises(ValueError, match="active provenance schema validation failed"):
        audit_active_manifest(base, lock, active, provenance)


def test_active_manifest_audit_rejects_rogue_manifest_field_with_recomputed_hash() -> None:
    base = _manifest("cond.alpha")
    lock = BaseManifestLock.from_manifest(
        base,
        source_commit="trusted",
        review_record_id="review-record",
    )
    active = {**base, "version": "active", "rogue_top_level": True}

    with pytest.raises(ValueError, match="ontology manifest schema validation failed"):
        audit_active_manifest(base, lock, active, _provenance(active, lock))


def test_evidence_tag_candidate_exposes_only_evidence_tag_operation() -> None:
    candidate = OntologyCandidate(
        candidate_id="cand-evidence",
        concept_id="cond.alpha",
        canonical_name="조건 A",
        candidate_aliases=["승인 밖 표현"],
        evidence_tags=["source:alpha"],
        retrieval={
            "expansion_rules": [{"match_any": ["A"], "expansion_terms": ["B"]}]
        },
        properties={"candidate_type": "evidence_tag", "target_concept_id": "cond.alpha"},
    )

    operations = project_candidate_operations(candidate, _manifest("cond.alpha"))

    assert [operation.path for operation in operations] == [
        f"/concepts/cond.alpha/evidence_tags/{canonical_json_hash('source:alpha')}"
    ]


def test_approval_patch_round_trip_preserves_semantic_operation() -> None:
    patch = ApprovalPatch.from_dict(
        {
            "schema_version": 1,
            "candidate_id": "cand-alpha",
            "candidate_payload_hash": "candidate-hash",
            "base_manifest_hash": "base-hash",
            "allowed_operations": [
                {
                    "operation": "add",
                    "path": "/concepts/cond.alpha/evidence_tags/value-hash",
                    "value_hash": "value-hash",
                }
            ],
            "approved_evidence": [{"chunk_id": "chunk:1", "content_hash": "evidence-hash"}],
            "reviewer": "tester",
            "reviewed_at": "2026-07-18T00:00:00+00:00",
        }
    )

    assert ApprovalPatch.from_dict(patch.to_dict()) == patch


@pytest.mark.parametrize(
    ("field", "replacement", "match"),
    [
        ("schema_version", 0, "schema_version"),
        ("candidate_id", "", "candidate_id"),
        ("candidate_payload_hash", "", "candidate_payload_hash"),
        ("base_manifest_hash", "", "base_manifest_hash"),
        ("reviewer", "", "reviewer"),
        ("reviewed_at", "", "reviewed_at"),
        ("allowed_operations", [], "allowed_operations"),
        ("allowed_operations", ["not-an-operation"], "allowed_operations"),
        ("approved_evidence", ["not-evidence"], "approved_evidence"),
    ],
)
def test_approval_patch_rejects_unsupported_or_unaccountable_artifact_fields(
    field: str,
    replacement: object,
    match: str,
) -> None:
    payload = {
        "schema_version": 1,
        "candidate_id": "cand-alpha",
        "candidate_payload_hash": "candidate-hash",
        "base_manifest_hash": "base-hash",
        "allowed_operations": [
            {
                "operation": "add",
                "path": "/concepts/cond.alpha/evidence_tags/value-hash",
                "value_hash": "value-hash",
            }
        ],
        "approved_evidence": [
            {"chunk_id": "chunk:1", "content_hash": "evidence-hash"}
        ],
        "reviewer": "tester",
        "reviewed_at": "2026-07-18T00:00:00+00:00",
    }
    payload[field] = replacement

    with pytest.raises(ValueError, match=match):
        ApprovalPatch.from_dict(payload)
