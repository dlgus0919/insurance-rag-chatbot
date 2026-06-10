from __future__ import annotations

from scripts.extract_ontology_candidates import mark_candidates_as_test
from src.ontology.review_store import OntologyCandidate


def test_mark_candidates_as_test_sets_explicit_development_flag() -> None:
    candidate = OntologyCandidate(
        candidate_id="dev.test",
        concept_id="cond.test",
        canonical_name="테스트 후보",
        properties={"extraction": {"policy_id": "candidate-extraction-default"}},
    )

    mark_candidates_as_test([candidate])

    assert candidate.test_candidate is True
    assert candidate.properties["extraction"]["policy_id"] == "candidate-extraction-default"
    assert candidate.properties["extraction"]["marked_test_candidate"] is True
    assert candidate.properties["extraction"]["test_candidate_reason"] == "explicit --mark-test-candidates"
