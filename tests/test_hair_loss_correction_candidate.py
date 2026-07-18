from __future__ import annotations

import json
from pathlib import Path

from src.ontology.review_store import OntologyCandidate, PENDING


ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "review_artifacts"
    / "2026-07-18-hair-loss-full-payload-correction-candidate.json"
)


def test_hair_loss_correction_artifact_is_pending_and_complete() -> None:
    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    candidate = OntologyCandidate.from_dict(payload)

    assert candidate.validate() == []
    assert candidate.status == PENDING
    assert candidate.test_candidate is False
    assert candidate.concept_id == "cov.hair_loss"
    assert "노화성 탈모" in candidate.aliases
    assert candidate.planner["clarification_questions"]
    assert candidate.planner["required_evidence"]
    assert candidate.retrieval["lexical_priority_terms"] == [
        "노화현상으로 인한 탈모",
        "탈모",
    ]

    decision = candidate.properties["source_grounded_decision"]
    assert decision["direct_source_chunk_ids"] == {
        "4th": ["약관_ch_002457"],
        "5th": ["표준약관_ch_005453"],
    }
    assert "standard_reference_note" not in decision
    assert {item["chunk_id"] for item in candidate.source_evidence} == {
        "약관_ch_002457",
        "표준약관_ch_005453",
    }
    assert candidate.properties["apply_mode"] == "update_existing_concept_after_practitioner_approval"
