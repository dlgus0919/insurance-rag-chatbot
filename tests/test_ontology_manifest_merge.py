from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ontology.manifest_merge import merge_approved_candidates
from src.ontology.review_store import APPROVED, OntologyCandidate, build_test_candidate


def write_base_manifest(path: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "version": "base-test",
        "concepts": [
            {
                "concept_id": "cond.base",
                "canonical_name": "기존 조건",
                "node_type": "ClaimCondition",
                "aliases": ["기존조건"],
                "planner": {"conditions": ["기존 조건"]},
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_merge_approved_candidates_writes_active_manifest(tmp_path: Path) -> None:
    base_path = tmp_path / "concepts.json"
    active_path = tmp_path / "concepts.active.json"
    write_base_manifest(base_path)
    candidate = build_test_candidate("test-cand")
    candidate.status = APPROVED

    result = merge_approved_candidates([candidate], base_manifest_path=base_path, output_path=active_path)

    payload = json.loads(active_path.read_text(encoding="utf-8"))
    assert result.base_concept_count == 1
    assert result.merged_candidate_count == 1
    assert result.total_concept_count == 2
    assert [item["concept_id"] for item in payload["concepts"]] == [
        "cond.base",
        "cond.test_practitioner_approval",
    ]
    assert payload["concepts"][1]["properties"]["approval_candidate_id"] == "test-cand"


def test_merge_approved_candidates_rejects_duplicate_concept_id(tmp_path: Path) -> None:
    base_path = tmp_path / "concepts.json"
    write_base_manifest(base_path)
    candidate = OntologyCandidate(
        candidate_id="dup",
        concept_id="cond.base",
        canonical_name="다른 조건",
        aliases=["다른조건"],
        status=APPROVED,
    )

    with pytest.raises(ValueError, match="duplicated concept_id"):
        merge_approved_candidates(
            [candidate],
            base_manifest_path=base_path,
            output_path=tmp_path / "concepts.active.json",
        )


def test_merge_approved_reinforcement_candidate_updates_existing_concept(tmp_path: Path) -> None:
    base_path = tmp_path / "concepts.json"
    active_path = tmp_path / "concepts.active.json"
    write_base_manifest(base_path)
    candidate = OntologyCandidate(
        candidate_id="reinforce",
        concept_id="cond.base",
        canonical_name="기존 조건",
        node_type="ClaimCondition",
        candidate_aliases=["새 표현"],
        evidence_tags=["candidate:새표현"],
        retrieval={"expansion_rules": [{"match_any": ["기존 조건"], "expansion_terms": ["새 표현"]}]},
        properties={"candidate_type": "alias_or_expansion", "target_concept_id": "cond.base"},
        status=APPROVED,
    )

    result = merge_approved_candidates([candidate], base_manifest_path=base_path, output_path=active_path)

    payload = json.loads(active_path.read_text(encoding="utf-8"))
    concept = payload["concepts"][0]
    assert result.total_concept_count == 1
    assert result.merged_candidate_count == 1
    assert concept["candidate_aliases"] == ["새 표현"]
    assert concept["evidence_tags"] == ["candidate:새표현"]
    assert concept["retrieval"]["expansion_rules"][0]["expansion_terms"] == ["새 표현"]
    assert concept["properties"]["approval_candidate_ids"] == ["reinforce"]


def test_merge_approved_candidates_rejects_alias_conflict(tmp_path: Path) -> None:
    base_path = tmp_path / "concepts.json"
    write_base_manifest(base_path)
    candidate = OntologyCandidate(
        candidate_id="alias-conflict",
        concept_id="cond.alias_conflict",
        canonical_name="신규 조건",
        aliases=["기존조건"],
        status=APPROVED,
    )

    with pytest.raises(ValueError, match="alias conflict"):
        merge_approved_candidates(
            [candidate],
            base_manifest_path=base_path,
            output_path=tmp_path / "concepts.active.json",
        )


def test_merge_allows_existing_base_alias_conflict_as_warning(tmp_path: Path) -> None:
    base_path = tmp_path / "concepts.json"
    active_path = tmp_path / "concepts.active.json"
    payload = {
        "schema_version": "1.0",
        "version": "base-test",
        "concepts": [
            {
                "concept_id": "cond.one",
                "canonical_name": "첫 조건",
                "aliases": ["공통 별칭"],
            },
            {
                "concept_id": "cond.two",
                "canonical_name": "둘째 조건",
                "aliases": ["공통 별칭"],
            },
        ],
    }
    base_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    candidate = OntologyCandidate(
        candidate_id="reinforce",
        concept_id="cond.one",
        canonical_name="첫 조건",
        candidate_aliases=["새 표현"],
        properties={"candidate_type": "alias_or_expansion", "target_concept_id": "cond.one"},
        status=APPROVED,
    )

    result = merge_approved_candidates([candidate], base_manifest_path=base_path, output_path=active_path)

    assert result.merged_candidate_count == 1
    assert result.warnings == ["base manifest existing alias conflict: 공통 별칭 maps to both cond.one and cond.two"]
