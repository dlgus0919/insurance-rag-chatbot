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
