from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ontology.approval_integrity import (
    ApprovalOperation,
    ApprovalPatchError,
    ApprovedEvidence,
    BaseManifestLock,
    LegacyApprovalUnverifiableError,
    StaleApprovalPatchError,
    build_approval_patch,
    project_candidate_operations,
)
from src.ontology.manifest_merge import merge_approved_candidates
from src.ontology.review_store import APPROVED, OntologyCandidate, build_test_candidate


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _base_payload(*, include_untrusted_delta: bool = False) -> dict[str, object]:
    concepts: list[dict[str, object]] = [
        {
            "concept_id": "cond.alpha",
            "canonical_name": "기존 조건",
            "node_type": "ClaimCondition",
            "aliases": ["기존조건"],
            "planner": {"conditions": ["기존 조건"]},
        }
    ]
    if include_untrusted_delta:
        concepts.append(
            {
                "concept_id": "cond.untrusted",
                "canonical_name": "검증되지 않은 조건",
            }
        )
    return {
        "schema_version": "1.0",
        "version": "base-test",
        "description": "trusted test manifest",
        "concepts": concepts,
    }


def _write_base(tmp_path: Path, *, include_untrusted_delta: bool = False) -> Path:
    path = tmp_path / "concepts.json"
    _write_json(path, _base_payload(include_untrusted_delta=include_untrusted_delta))
    return path


def _write_lock(tmp_path: Path) -> Path:
    path = tmp_path / "base_manifest.lock.json"
    lock = BaseManifestLock.from_manifest(
        _base_payload(),
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    lock.write(path)
    return path


def _manifest(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _concept(path: Path, concept_id: str) -> dict[str, object]:
    payload = _manifest(path)
    return next(
        item
        for item in payload["concepts"]
        if isinstance(item, dict) and item.get("concept_id") == concept_id
    )


def _paths_for(candidate: OntologyCandidate, base: dict[str, object], field: str) -> list[str]:
    return [
        operation.path
        for operation in project_candidate_operations(candidate, base)
        if f"/{field}/" in operation.path or operation.path.endswith(f"/{field}")
    ]


def _approval_patch(
    candidate: OntologyCandidate,
    base: dict[str, object],
    *,
    fields: tuple[str, ...],
):
    paths: list[str] = []
    for field in fields:
        paths.extend(_paths_for(candidate, base, field))
    return build_approval_patch(
        candidate,
        base,
        approved_paths=paths,
        reviewer="tester",
        reviewed_at="2026-07-18T00:00:00+00:00",
    )


def _approved_evidence_candidate() -> OntologyCandidate:
    return OntologyCandidate(
        candidate_id="cand-evidence",
        concept_id="cond.alpha",
        canonical_name="기존 조건",
        aliases=["승인 밖 별칭"],
        candidate_aliases=["승인 밖 후보 표현"],
        evidence_tags=["source:alpha"],
        planner={"clarification_questions": ["추가 확인 질문"]},
        retrieval={
            "expansion_rules": [
                {"match_any": ["기존 조건"], "expansion_terms": ["확장 표현"]}
            ],
            "lexical_priority_terms": ["우선 검색어"],
        },
        runtime_properties={"source_grounded_decision": {"status": "internal"}},
        source_evidence=[{"chunk_id": "chunk-alpha", "excerpt": "근거 원문"}],
        properties={"candidate_type": "evidence_tag", "target_concept_id": "cond.alpha"},
        status=APPROVED,
    )


def _merge(
    tmp_path: Path,
    candidates: list[OntologyCandidate],
    patches: dict[str, object],
    *,
    base_path: Path | None = None,
) -> tuple[object, Path, Path]:
    base = base_path or _write_base(tmp_path)
    active = tmp_path / "concepts.active.json"
    provenance = tmp_path / "concepts.active.provenance.json"
    result = merge_approved_candidates(
        candidates,
        approval_patches=patches,
        base_manifest_path=base,
        base_lock_path=_write_lock(tmp_path),
        output_path=active,
        provenance_path=provenance,
    )
    return result, active, provenance


def test_evidence_only_patch_cannot_promote_alias_question_retrieval_or_decision_profile(
    tmp_path: Path,
) -> None:
    base_path = _write_base(tmp_path, include_untrusted_delta=True)
    candidate = _approved_evidence_candidate()
    patch = _approval_patch(candidate, _base_payload(), fields=("evidence_tags",))

    result, active, _provenance = _merge(
        tmp_path,
        [candidate],
        {candidate.candidate_id: patch},
        base_path=base_path,
    )

    concept = _concept(active, "cond.alpha")
    assert concept["evidence_tags"] == ["source:alpha"]
    assert "aliases" not in concept or concept["aliases"] == ["기존조건"]
    assert "candidate_aliases" not in concept
    assert "clarification_questions" not in concept.get("planner", {})
    assert "retrieval" not in concept
    assert "source_grounded_decision" not in concept.get("properties", {})
    assert "cond.untrusted" not in [item["concept_id"] for item in _manifest(active)["concepts"]]
    assert result.applied_operation_count == 1
    assert result.quarantined_concept_ids == ("cond.untrusted",)


def test_merge_rejects_approved_candidate_without_field_level_patch(tmp_path: Path) -> None:
    candidate = _approved_evidence_candidate()

    with pytest.raises(LegacyApprovalUnverifiableError, match=candidate.candidate_id):
        _merge(tmp_path, [candidate], {})


def test_merge_rejects_patch_after_candidate_payload_changes(tmp_path: Path) -> None:
    candidate = _approved_evidence_candidate()
    patch = _approval_patch(candidate, _base_payload(), fields=("evidence_tags",))
    candidate.candidate_aliases.append("승인 후 변경")

    with pytest.raises(StaleApprovalPatchError, match=candidate.candidate_id):
        _merge(tmp_path, [candidate], {candidate.candidate_id: patch})


@pytest.mark.parametrize(
    ("field", "replacement", "match"),
    [
        ("schema_version", 0, "schema_version"),
        ("reviewer", "", "reviewer"),
        ("reviewed_at", "", "reviewed_at"),
        ("allowed_operations", (), "allowed_operations"),
        ("allowed_operations", ("not-an-operation",), "allowed_operations"),
    ],
)
def test_merge_revalidates_in_memory_approval_patch_before_apply(
    tmp_path: Path,
    field: str,
    replacement: object,
    match: str,
) -> None:
    candidate = _approved_evidence_candidate()
    patch = _approval_patch(candidate, _base_payload(), fields=("evidence_tags",))
    object.__setattr__(patch, field, replacement)

    with pytest.raises(ApprovalPatchError, match=match):
        _merge(tmp_path, [candidate], {candidate.candidate_id: patch})

    assert not (tmp_path / "concepts.active.json").exists()


def test_merge_rejects_stale_patch_evidence_before_apply(tmp_path: Path) -> None:
    candidate = _approved_evidence_candidate()
    patch = _approval_patch(candidate, _base_payload(), fields=("evidence_tags",))
    object.__setattr__(
        patch,
        "approved_evidence",
        (ApprovedEvidence(chunk_id="chunk-alpha", content_hash="stale-evidence"),),
    )

    with pytest.raises(StaleApprovalPatchError, match="evidence is stale"):
        _merge(tmp_path, [candidate], {candidate.candidate_id: patch})

    assert not (tmp_path / "concepts.active.json").exists()


def test_merge_rejects_stale_patch_base_before_apply(tmp_path: Path) -> None:
    candidate = _approved_evidence_candidate()
    patch = _approval_patch(candidate, _base_payload(), fields=("evidence_tags",))
    object.__setattr__(patch, "base_manifest_hash", "stale-base")

    with pytest.raises(StaleApprovalPatchError, match="base manifest is stale"):
        _merge(tmp_path, [candidate], {candidate.candidate_id: patch})

    assert not (tmp_path / "concepts.active.json").exists()


def test_merge_rejects_unsupported_approval_path_before_apply(tmp_path: Path) -> None:
    candidate = _approved_evidence_candidate()
    patch = _approval_patch(candidate, _base_payload(), fields=("evidence_tags",))
    operation = patch.allowed_operations[0]
    object.__setattr__(
        patch,
        "allowed_operations",
        (
            ApprovalOperation(
                operation=operation.operation,
                path="/concepts/cond.alpha/unsupported/value-hash",
                value_hash=operation.value_hash,
            ),
        ),
    )

    with pytest.raises(StaleApprovalPatchError, match="operation is stale"):
        _merge(tmp_path, [candidate], {candidate.candidate_id: patch})

    assert not (tmp_path / "concepts.active.json").exists()


def test_merge_is_idempotent_for_same_approved_patch_inputs(tmp_path: Path) -> None:
    candidate = build_test_candidate("cand-new")
    candidate.status = APPROVED
    base = _base_payload()
    patch = _approval_patch(
        candidate,
        base,
        fields=("canonical_name", "node_type", "aliases"),
    )

    first, _active_one, provenance_one = _merge(
        tmp_path / "first",
        [candidate],
        {candidate.candidate_id: patch},
    )
    second, _active_two, provenance_two = _merge(
        tmp_path / "second",
        [candidate],
        {candidate.candidate_id: patch},
    )

    assert first.active_content_hash == second.active_content_hash
    assert _manifest(provenance_one)["applied_operations"] == _manifest(provenance_two)["applied_operations"]


def test_merge_allows_only_schema_supported_generic_planner_and_retrieval_fields(
    tmp_path: Path,
) -> None:
    candidate = OntologyCandidate(
        candidate_id="cand-generic-fields",
        concept_id="cond.generic_fields",
        canonical_name="일반 검토 개념",
        node_type="ClaimCondition",
        planner={
            "clarification_questions": ["추가 확인 질문"],
            "required_evidence": ["확인 서류"],
        },
        retrieval={"lexical_priority_terms": ["핵심 검색어"]},
        properties={"candidate_type": "new_concept"},
        status=APPROVED,
    )
    patch = _approval_patch(
        candidate,
        _base_payload(),
        fields=("canonical_name", "node_type", "planner", "retrieval"),
    )

    _result, active, _provenance = _merge(
        tmp_path,
        [candidate],
        {candidate.candidate_id: patch},
    )

    concept = _concept(active, candidate.concept_id)
    assert concept["planner"] == {
        "clarification_questions": ["추가 확인 질문"],
        "required_evidence": ["확인 서류"],
    }
    assert concept["retrieval"] == {"lexical_priority_terms": ["핵심 검색어"]}


def test_merge_rejects_alias_conflict_introduced_by_approved_patch(tmp_path: Path) -> None:
    candidate = OntologyCandidate(
        candidate_id="alias-conflict",
        concept_id="cond.alias_conflict",
        canonical_name="신규 조건",
        aliases=["기존조건"],
        properties={"candidate_type": "new_concept"},
        status=APPROVED,
    )
    patch = _approval_patch(
        candidate,
        _base_payload(),
        fields=("canonical_name", "aliases"),
    )

    with pytest.raises(ValueError, match="alias conflict"):
        _merge(tmp_path, [candidate], {candidate.candidate_id: patch})


def test_merge_allows_existing_base_alias_conflict_as_warning(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["concepts"].append(
        {
            "concept_id": "cond.beta",
            "canonical_name": "둘째 조건",
            "aliases": ["기존조건"],
        }
    )
    base_path = tmp_path / "concepts.json"
    _write_json(base_path, payload)
    lock = BaseManifestLock.from_manifest(
        payload,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    lock_path = tmp_path / "base_manifest.lock.json"
    lock.write(lock_path)
    candidate = _approved_evidence_candidate()
    patch = _approval_patch(candidate, payload, fields=("evidence_tags",))
    active = tmp_path / "concepts.active.json"

    result = merge_approved_candidates(
        [candidate],
        approval_patches={candidate.candidate_id: patch},
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        output_path=active,
        provenance_path=tmp_path / "concepts.active.provenance.json",
    )

    assert result.applied_operation_count == 1
    assert result.warnings == [
        "base manifest existing alias conflict: 기존조건 maps to both cond.alpha and cond.beta"
    ]


def test_merge_rejects_duplicate_candidate_alias_across_concepts(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["concepts"].append(
        {"concept_id": "cov.beta", "canonical_name": "둘째 보장"}
    )
    base_path = tmp_path / "concepts.json"
    _write_json(base_path, payload)
    lock = BaseManifestLock.from_manifest(
        payload,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    lock_path = tmp_path / "base_manifest.lock.json"
    lock.write(lock_path)
    candidates = [
        OntologyCandidate(
            candidate_id="cand-one",
            concept_id="cond.alpha",
            canonical_name="기존 조건",
            candidate_aliases=["비급여 주사제"],
            properties={"candidate_type": "alias_or_expansion", "target_concept_id": "cond.alpha"},
            status=APPROVED,
        ),
        OntologyCandidate(
            candidate_id="cand-two",
            concept_id="cov.beta",
            canonical_name="둘째 보장",
            candidate_aliases=["비급여 주사제"],
            properties={"candidate_type": "alias_or_expansion", "target_concept_id": "cov.beta"},
            status=APPROVED,
        ),
    ]
    patches = {
        candidate.candidate_id: _approval_patch(candidate, payload, fields=("candidate_aliases",))
        for candidate in candidates
    }

    with pytest.raises(ValueError, match="candidate_alias quality conflict"):
        merge_approved_candidates(
            candidates,
            approval_patches=patches,
            base_manifest_path=base_path,
            base_lock_path=lock_path,
            output_path=tmp_path / "concepts.active.json",
            provenance_path=tmp_path / "concepts.active.provenance.json",
        )


def test_merge_rejects_sentence_fragment_candidate_alias(tmp_path: Path) -> None:
    candidate = OntologyCandidate(
        candidate_id="fragment",
        concept_id="cond.alpha",
        canonical_name="기존 조건",
        candidate_aliases=["질병의 치료 목적에 해당되어"],
        properties={"candidate_type": "alias_or_expansion", "target_concept_id": "cond.alpha"},
        status=APPROVED,
    )
    patch = _approval_patch(candidate, _base_payload(), fields=("candidate_aliases",))

    with pytest.raises(ValueError, match="sentence-like evidence text"):
        _merge(tmp_path, [candidate], {candidate.candidate_id: patch})
