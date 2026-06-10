#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ontology.candidate_extractor import (
    extract_reinforcement_candidates,
    load_graph_evidence,
    load_manifest_concepts,
    load_processed_chunks,
)
from src.ontology.llm_batch import LlmBatchConfig, maybe_start_llm_server, maybe_stop_llm_server
from src.ontology.policy import load_candidate_extraction_policy, load_review_policy, validate_policy_files
from src.ontology.registry import BASE_ONTOLOGY_MANIFEST
from src.ontology.review_store import DEFAULT_CANDIDATES_PATH, OntologyReviewStore, utc_now_iso


DEFAULT_SOURCES = [
    ROOT / "data" / "processed" / "chunks_canonical_manifest.jsonl",
    ROOT / "data" / "processed" / "chunks.jsonl",
]
DEFAULT_GRAPH_DB = ROOT / "data" / "index" / "graph" / "insurance_graph.sqlite"


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract pending ontology review candidates from project data.")
    parser.add_argument("--source", action="append", default=[], help="Processed chunk JSONL source. Can be repeated.")
    parser.add_argument("--graph-db", default=str(DEFAULT_GRAPH_DB), help="Optional GraphDB SQLite evidence source.")
    parser.add_argument("--manifest", default=str(BASE_ONTOLOGY_MANIFEST), help="Base ontology manifest path.")
    parser.add_argument("--output", default=str(DEFAULT_CANDIDATES_PATH), help="Candidate JSONL output path.")
    parser.add_argument("--dry-run", action="store_true", help="Print candidates without writing candidates.jsonl.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum candidates to generate.")
    parser.add_argument("--source-limit", type=int, default=2000, help="Maximum source chunks/evidence rows to scan.")
    parser.add_argument("--candidate-type", default=None, help="Candidate type to generate in this MVP.")
    parser.add_argument("--candidate-policy", default=None, help="Candidate extraction policy JSON path.")
    parser.add_argument("--review-policy", default=None, help="Ontology review policy JSON path.")
    parser.add_argument("--validate-policies", action="store_true", help="Validate ontology policy files before extraction.")
    parser.add_argument("--template-only", action="store_true", help="Generate display metadata without LLM calls.")
    parser.add_argument("--llm", choices=["auto", "none", "sglang", "vllm"], default="none")
    parser.add_argument("--model", default="qwen3-next-80b-a3b-instruct-fp8")
    parser.add_argument("--start-llm", action="store_true", help="Start/switch the selected DGX local LLM before extraction.")
    parser.add_argument("--stop-llm-after", action="store_true", help="Stop the LLM tmux session after extraction.")
    parser.add_argument("--llm-base-url", default=None)
    parser.add_argument("--llm-timeout", type=int, default=1800)
    parser.add_argument("--replace-existing", action="store_true", help="Replace existing candidates with the same id.")
    args = parser.parse_args()

    candidate_policy = load_candidate_extraction_policy(args.candidate_policy)
    review_policy = load_review_policy(args.review_policy)
    policy_validation = None
    if args.validate_policies:
        policy_validation = validate_policy_files(
            candidate_policy_path=args.candidate_policy,
            review_policy_path=args.review_policy,
        )
    candidate_type = args.candidate_type or candidate_policy.default_reinforcement_type
    if candidate_type != "alias_or_expansion":
        raise SystemExit("Phase 5 MVP currently supports --candidate-type alias_or_expansion only")

    sources = [Path(path) for path in args.source] or DEFAULT_SOURCES
    llm_config = LlmBatchConfig(
        llm="none" if args.template_only else args.llm,
        model=args.model,
        start_llm=args.start_llm,
        stop_llm_after=args.stop_llm_after,
        llm_base_url=args.llm_base_url,
        timeout=args.llm_timeout,
    )
    selection = maybe_start_llm_server(llm_config, dry_run=args.dry_run)
    try:
        concepts = load_manifest_concepts(args.manifest)
        chunks = load_processed_chunks(sources, limit=args.source_limit)
        graph_limit = max(args.source_limit - len(chunks), 0) if args.source_limit else None
        chunks.extend(load_graph_evidence(args.graph_db, limit=graph_limit))
        result = extract_reinforcement_candidates(
            concepts=concepts,
            chunks=chunks,
            extraction_run_id=f"ontology-candidate-extract-{utc_now_iso()}",
            candidate_limit=args.limit,
            candidate_type=candidate_type,
            extraction_policy=candidate_policy,
            review_policy=review_policy,
        )
        saved = 0
        skipped_existing: list[str] = []
        if not args.dry_run:
            store = OntologyReviewStore(candidates_path=args.output)
            for candidate in result.candidates:
                try:
                    store.add_candidate(candidate, replace=args.replace_existing)
                    saved += 1
                except ValueError as exc:
                    if "candidate already exists" in str(exc):
                        skipped_existing.append(candidate.candidate_id)
                        continue
                    raise
        print(
            _json(
                {
                    "dry_run": args.dry_run,
                    "source_count": result.source_count,
                    "generated_count": len(result.candidates),
                    "saved_count": saved,
                    "skipped_existing": skipped_existing,
                    "warnings": result.warnings,
                    "policy_validation": policy_validation,
                    "llm": {
                        "mode": llm_config.llm,
                        "selected_provider": selection.provider if selection else None,
                        "selected_model": selection.model if selection else None,
                        "base_url": selection.base_url if selection else None,
                        "template_only": args.template_only,
                    },
                    "candidates": [candidate.to_dict() for candidate in result.candidates],
                }
            )
        )
    finally:
        maybe_stop_llm_server(llm_config, selection, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
