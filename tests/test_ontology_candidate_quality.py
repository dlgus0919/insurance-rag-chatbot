from __future__ import annotations

from src.ontology.candidate_quality import sanitize_candidate_aliases
from src.ontology.review_store import OntologyCandidate


def test_sanitize_candidate_aliases_removes_fragments_and_multi_owner_aliases() -> None:
    candidates = [
        OntologyCandidate(
            candidate_id="one",
            concept_id="cov.one",
            canonical_name="첫 보장",
            candidate_aliases=["즉 비급여 도수치료", "비급여 주사제", "단일 표현"],
        ),
        OntologyCandidate(
            candidate_id="two",
            concept_id="cov.two",
            canonical_name="둘째 보장",
            candidate_aliases=["비급여 주사제", "다른 표현"],
        ),
    ]

    sanitized, changes = sanitize_candidate_aliases(candidates)

    assert sanitized[0].candidate_aliases == ["단일 표현"]
    assert sanitized[1].candidate_aliases == ["다른 표현"]
    assert len(changes) == 2
    assert sanitized[0].properties["quality_repair"]["repair_policy"] == "remove_sentence_fragments_and_multi_owner_aliases"
    removed = sanitized[0].properties["quality_repair"]["removed_candidate_aliases"]
    assert {"alias": "즉 비급여 도수치료", "reason": "sentence_fragment_alias"} in removed
    assert {"alias": "비급여 주사제", "reason": "candidate_alias_multi_owner"} in removed
