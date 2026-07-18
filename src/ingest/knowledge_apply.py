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
from src.ingest.source_promotion import (
    ACTIVE_SOURCE_CHUNKS_PATH,
    IntakeSourceRef,
    collect_approved_intake_source_refs,
    promote_staging_chunks,
    validate_staging_source_refs,
)
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
    sources: list[dict[str, Any]]
    index_rebuilt: bool
    graph_rebuilt: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_ontology_reviews(*, dry_run: bool = False) -> dict[str, Any]:
    store = OntologyReviewStore()
    try:
        result = apply_reviews(store, rebuild_graph=False, dry_run=dry_run)
    except ValueError as exc:
        return {"skipped": True, "reason": str(exc)}
    payload = result.to_dict(rebuild_graph=False)
    payload.update(
        {
            "skipped": False,
            "dry_run": dry_run,
            "output_path": (
                str(result.merge_result.output_path) if result.merge_result is not None else ""
            ),
            "base_concept_count": (
                result.merge_result.base_concept_count if result.merge_result is not None else 0
            ),
            "merged_candidate_count": (
                result.merge_result.merged_candidate_count if result.merge_result is not None else 0
            ),
            "total_concept_count": (
                result.merge_result.total_concept_count if result.merge_result is not None else 0
            ),
        }
    )
    return payload


def apply_rule_candidates(*, dry_run: bool = False) -> dict[str, Any]:
    return apply_candidates(
        candidates_path=DEFAULT_RULE_CANDIDATES_PATH,
        review_log_path=DEFAULT_RULE_REVIEW_LOG_PATH,
        rules_path=DEFAULT_RULES_PATH,
        links_path=DEFAULT_RULE_LINKS_PATH,
        dry_run=dry_run,
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
            "--active-source-chunks",
            str(ACTIVE_SOURCE_CHUNKS_PATH),
        ],
        cwd=config.ROOT_DIR,
        env=env,
        check=True,
    )


def rebuild_search_indexes() -> None:
    for index_mode in ("v2_only", "v1_v2_combined"):
        subprocess.run(
            [
                sys.executable,
                "scripts/build_index_from_canonical_manifest.py",
                "--index-mode",
                index_mode,
                "--active-source-chunks",
                str(ACTIVE_SOURCE_CHUNKS_PATH),
            ],
            cwd=config.ROOT_DIR,
            check=True,
        )


def promote_approved_sources(refs: list[IntakeSourceRef]) -> list[dict[str, Any]]:
    validate_staging_source_refs(refs)
    results = []
    for ref in refs:
        result = promote_staging_chunks(
            job_id=ref.job_id,
            staging_chunks_path=ref.staging_chunks_path,
            source_filename=ref.source_filename,
        )
        results.append(asdict(result))
    return results


def apply_approved_knowledge() -> KnowledgeApplyResult:
    ontology_preflight: dict[str, Any] = {}
    try:
        ontology_preflight = apply_ontology_reviews(dry_run=True)
        if not ontology_preflight.get("valid", False):
            raise RuntimeError("ontology integrity preflight failed")
        apply_rule_candidates(dry_run=True)
        refs = collect_approved_intake_source_refs(
            OntologyReviewStore().candidates_path,
            DEFAULT_RULE_CANDIDATES_PATH,
        )
        source_results = promote_approved_sources(refs)
    except Exception as exc:
        return KnowledgeApplyResult(
            status="failed_preflight",
            ontology=ontology_preflight,
            rules={"error": str(exc), "error_type": type(exc).__name__},
            sources=[{"error": str(exc), "error_type": type(exc).__name__}],
            index_rebuilt=False,
            graph_rebuilt=False,
        )

    ontology = apply_ontology_reviews(dry_run=False)
    rules = apply_rule_candidates(dry_run=False)
    rebuild_search_indexes()
    rebuild_graph()
    return KnowledgeApplyResult(
        status="completed",
        ontology=ontology,
        rules=rules,
        sources=source_results,
        index_rebuilt=True,
        graph_rebuilt=True,
    )
