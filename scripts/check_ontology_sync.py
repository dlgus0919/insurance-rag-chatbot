from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ontology.registry import OntologyRegistry
from src.ontology.candidate_quality import find_manifest_candidate_alias_issues


def check_registry(registry: OntologyRegistry) -> list[str]:
    errors: list[str] = []
    integrity = registry.integrity_summary()
    if integrity["state"] != "valid":
        errors.append(f"ontology integrity state is {integrity['state']}")
    concept_ids = {concept.concept_id for concept in registry.concepts}
    if len(concept_ids) != len(registry.concepts):
        errors.append("duplicated concept_id exists")

    for concept in registry.concepts:
        has_planner_mapping = bool(
            concept.planner_coverage_topics
            or concept.planner_conditions
            or concept.planner_claim_unit_terms
            or concept.evidence_tags
        )
        has_retrieval_rule = bool(concept.retrieval_expansion_rules)
        if has_retrieval_rule and not has_planner_mapping:
            errors.append(f"{concept.concept_id}: retrieval expansion exists without planner mapping")
        if concept.candidate_aliases and not has_planner_mapping:
            errors.append(f"{concept.concept_id}: candidate aliases exist without planner mapping")
        if concept.node_type and not concept.canonical_name:
            errors.append(f"{concept.concept_id}: graph seed node requires canonical_name")

    for issue in find_manifest_candidate_alias_issues(registry.concepts):
        if issue.severity == "error":
            errors.append(issue.message)

    diagnostics = registry.diagnostics()
    if diagnostics["concept_count"] == 0:
        errors.append("ontology manifest has no concepts")
    if diagnostics["alias_count"] == 0:
        errors.append("ontology manifest has no aliases")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate insurance ontology manifest sync invariants.")
    parser.add_argument("--manifest", type=Path, default=None, help="Path to ontology concepts manifest JSON.")
    args = parser.parse_args()

    registry = OntologyRegistry(args.manifest) if args.manifest else OntologyRegistry()
    errors = check_registry(registry)
    if errors:
        print("[FAIL] Ontology sync check failed")
        for error in errors:
            print(f"- {error}")
        return 1

    diagnostics = registry.diagnostics()
    print("[OK] Ontology sync check passed")
    print(
        "concepts={concept_count} aliases={alias_count} "
        "candidate_aliases={candidate_alias_count} retrieval_rules={retrieval_rule_count}".format(**diagnostics)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
