"""Apply approved knowledge-review items to active runtime assets."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any

from scripts.claim_rule_candidate_review import apply_candidates
from scripts.ontology_review import (
    ACTIVE_ONTOLOGY_MANIFEST,
    GRAPH_DB_PATH,
    GRAPH_MANIFEST_PATH,
    apply_reviews,
)
from src import config
from src.ontology.review_store import OntologyReviewStore

DEFAULT_RULE_CANDIDATES_PATH = config.ROOT_DIR / "data" / "rules" / "review" / "candidates.jsonl"
DEFAULT_RULE_REVIEW_LOG_PATH = config.ROOT_DIR / "data" / "rules" / "review" / "review_log.jsonl"
DEFAULT_RULES_PATH = config.ROOT_DIR / "data" / "rules" / "claim_deductible_rules.active.json"
DEFAULT_RULE_LINKS_PATH = config.ROOT_DIR / "data" / "rules" / "rule_links.active.json"


@dataclass(frozen=True)
class KnowledgeApplyResult:
    status: str
    ontology: dict[str, Any]
    rules: dict[str, Any]
    graph_rebuilt: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_ontology_reviews() -> dict[str, Any]:
    store = OntologyReviewStore()
    try:
        result = apply_reviews(store, rebuild_graph=False, dry_run=False)
    except ValueError as exc:
        return {"skipped": True, "reason": str(exc)}
    return {
        "skipped": False,
        "output_path": str(result.output_path),
        "base_concept_count": result.base_concept_count,
        "merged_candidate_count": result.merged_candidate_count,
        "total_concept_count": result.total_concept_count,
        "warnings": result.warnings,
    }


def apply_rule_candidates() -> dict[str, Any]:
    return apply_candidates(
        candidates_path=DEFAULT_RULE_CANDIDATES_PATH,
        review_log_path=DEFAULT_RULE_REVIEW_LOG_PATH,
        rules_path=DEFAULT_RULES_PATH,
        links_path=DEFAULT_RULE_LINKS_PATH,
        dry_run=False,
    )


def rebuild_graph() -> None:
    env = os.environ.copy()
    env["INSURANCE_ONTOLOGY_MANIFEST"] = str(ACTIVE_ONTOLOGY_MANIFEST)
    subprocess.run(
        [
            sys.executable,
            "scripts/build_graph_index.py",
            "--rebuild",
            "--output",
            str(GRAPH_DB_PATH),
            "--manifest",
            str(GRAPH_MANIFEST_PATH),
        ],
        cwd=config.ROOT_DIR,
        env=env,
        check=True,
    )


def apply_approved_knowledge() -> KnowledgeApplyResult:
    ontology = apply_ontology_reviews()
    rules = apply_rule_candidates()
    rebuild_graph()
    return KnowledgeApplyResult(
        status="completed",
        ontology=ontology,
        rules=rules,
        graph_rebuilt=True,
    )
