#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ontology.manifest_merge import ManifestMergeResult, merge_approved_candidates
from src.ontology.registry import ACTIVE_ONTOLOGY_MANIFEST, BASE_ONTOLOGY_MANIFEST
from src.ontology.review_store import (
    APPROVED,
    APPLIED,
    OntologyCandidate,
    OntologyReviewStore,
    build_test_candidate,
    utc_now_iso,
)

GRAPH_DB_PATH = ROOT / "data" / "index" / "graph" / "insurance_graph.sqlite"
GRAPH_MANIFEST_PATH = ROOT / "data" / "index" / "graph" / "insurance_graph_manifest.json"
ONTOLOGY_BACKUP_DIR = ROOT / "data" / "ontology" / "backups"
GRAPH_BACKUP_DIR = ROOT / "data" / "index" / "graph" / "backups"
REBUILD_LOCK_PATH = Path(os.getenv("INSURANCE_ONTOLOGY_REBUILD_LOCK", "/tmp/insurance-rag-ontology-rebuild.lock"))


@contextmanager
def rebuild_lock() -> Iterator[None]:
    REBUILD_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REBUILD_LOCK_PATH.open("w", encoding="utf-8") as lock_file:
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - non-POSIX fallback.
            pass
        yield


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _backup_file(path: Path, backup_dir: Path) -> Path | None:
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.name}.{utc_now_iso().replace(':', '').replace('+', 'Z')}.bak"
    shutil.copy2(path, backup_path)
    return backup_path


def _print_candidate(candidate: OntologyCandidate) -> None:
    evidence = candidate.source_evidence[0] if candidate.source_evidence else {}
    excerpt = str(evidence.get("excerpt") or "").replace("\n", " ").strip()
    doc = str(evidence.get("doc_short") or evidence.get("doc_name") or "").strip()
    page = str(evidence.get("page") or "").strip()
    print(f"ID: {candidate.candidate_id}")
    print(f"개념: {candidate.canonical_name} ({candidate.concept_id})")
    print(f"타입: {candidate.node_type or '-'}")
    print(f"상태: {candidate.status}")
    print(f"테스트 후보: {'예' if candidate.test_candidate else '아니오'}")
    print(f"별칭: {', '.join(candidate.aliases) if candidate.aliases else '-'}")
    print(f"위험 플래그: {', '.join(candidate.risk_flags) if candidate.risk_flags else '-'}")
    print(f"근거: {doc or '-'} {('p.' + page) if page else ''}")
    print(f"발췌: {excerpt or '-'}")


def _list_zenity_rows(candidates: list[OntologyCandidate]) -> None:
    for candidate in candidates:
        evidence = candidate.source_evidence[0] if candidate.source_evidence else {}
        doc = str(evidence.get("doc_short") or evidence.get("doc_name") or "-").strip()
        page = str(evidence.get("page") or "").strip()
        risk = ",".join(candidate.risk_flags) if candidate.risk_flags else "-"
        print(candidate.candidate_id)
        print(candidate.canonical_name)
        print(candidate.node_type or "-")
        print(candidate.status)
        print("test" if candidate.test_candidate else "production")
        print(f"{doc}{(' p.' + page) if page else ''}")
        print(risk)


def _validate_active_manifest(manifest_path: Path) -> None:
    cmd = [sys.executable, "scripts/check_ontology_sync.py", "--manifest", str(manifest_path)]
    subprocess.run(cmd, cwd=ROOT, check=True)


def _rebuild_graph(manifest_path: Path) -> None:
    _backup_file(GRAPH_DB_PATH, GRAPH_BACKUP_DIR)
    env = os.environ.copy()
    env["INSURANCE_ONTOLOGY_MANIFEST"] = str(manifest_path)
    cmd = [
        sys.executable,
        "scripts/build_graph_index.py",
        "--rebuild",
        "--output",
        str(GRAPH_DB_PATH),
        "--manifest",
        str(GRAPH_MANIFEST_PATH),
    ]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def apply_reviews(
    store: OntologyReviewStore,
    *,
    rebuild_graph: bool = False,
    dry_run: bool = False,
) -> ManifestMergeResult:
    candidates = store.approved_or_applied_candidates()
    if not candidates:
        raise ValueError("approved/applied ontology candidates do not exist")

    with rebuild_lock():
        if dry_run:
            return ManifestMergeResult(
                output_path=ACTIVE_ONTOLOGY_MANIFEST,
                base_concept_count=0,
                merged_candidate_count=len(candidates),
                total_concept_count=0,
                warnings=["dry_run: manifest was not written"],
            )
        _backup_file(ACTIVE_ONTOLOGY_MANIFEST, ONTOLOGY_BACKUP_DIR)
        result = merge_approved_candidates(
            candidates,
            base_manifest_path=BASE_ONTOLOGY_MANIFEST,
            output_path=ACTIVE_ONTOLOGY_MANIFEST,
        )
        _validate_active_manifest(result.output_path)
        if rebuild_graph:
            _rebuild_graph(result.output_path)
        store.mark_approved_as_applied(manifest_path=result.output_path)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Review and apply ontology candidates.")
    parser.add_argument("--pending-count", action="store_true", help="Print pending candidate count.")
    parser.add_argument("--summary", action="store_true", help="Print review candidate status summary.")
    parser.add_argument("--list-json", action="store_true", help="Print candidates as JSON.")
    parser.add_argument("--list-ids", action="store_true", help="Print candidate ids, one per line.")
    parser.add_argument("--list-zenity", action="store_true", help="Print pending candidates as newline-separated zenity rows.")
    parser.add_argument("--status", choices=["pending", "approved", "held", "rejected", "applied"], default=None)
    parser.add_argument("--show", metavar="CANDIDATE_ID", help="Show a human-readable candidate detail.")
    parser.add_argument("--seed-test-candidate", action="store_true", help="Create or replace one test-only ontology candidate.")
    parser.add_argument("--decide", metavar="CANDIDATE_ID", help="Candidate id to decide.")
    parser.add_argument("--decision", choices=["approve", "hold", "reject"], help="Decision for --decide.")
    parser.add_argument("--reviewer", default="practitioner", help="Reviewer name for audit log.")
    parser.add_argument("--reviewer-type", default="practitioner", help="Reviewer type for audit log.")
    parser.add_argument("--reason", default="", help="Decision reason.")
    parser.add_argument("--auto-approve-test", action="store_true", help="Approve pending test_candidate=true candidates only.")
    parser.add_argument("--apply", action="store_true", help="Generate active manifest from approved/applied candidates.")
    parser.add_argument("--rebuild-graph", action="store_true", help="Rebuild GraphDB after --apply.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned operations without mutating files.")
    args = parser.parse_args()

    store = OntologyReviewStore()

    if args.seed_test_candidate:
        candidate = build_test_candidate()
        if not args.dry_run:
            store.add_candidate(candidate, replace=True)
        print(_json({"seeded": not args.dry_run, "candidate": candidate.to_dict()}))

    if args.pending_count:
        print(len(store.pending_candidates()))

    if args.summary:
        print(_json(store.summary()))

    if args.list_json:
        candidates = store.load_candidates()
        if args.status:
            candidates = [candidate for candidate in candidates if candidate.status == args.status]
        print(_json([candidate.to_dict() for candidate in candidates]))

    if args.list_ids:
        candidates = store.load_candidates()
        if args.status:
            candidates = [candidate for candidate in candidates if candidate.status == args.status]
        for candidate in candidates:
            print(candidate.candidate_id)

    if args.list_zenity:
        candidates = store.pending_candidates()
        _list_zenity_rows(candidates)

    if args.show:
        _print_candidate(store.get_candidate(args.show))

    if args.decide:
        if not args.decision:
            parser.error("--decision is required with --decide")
        if args.dry_run:
            print(_json({"candidate_id": args.decide, "decision": args.decision, "dry_run": True}))
        else:
            candidate = store.decide(
                args.decide,
                args.decision,
                reviewer=args.reviewer,
                reviewer_type=args.reviewer_type,
                reason=args.reason,
            )
            print(_json({"updated": candidate.to_dict()}))

    if args.auto_approve_test:
        selected = store.auto_approve_test_candidates(reviewer=args.reviewer, dry_run=args.dry_run)
        print(_json({"auto_approved_test_candidates": [candidate.candidate_id for candidate in selected], "dry_run": args.dry_run}))

    if args.apply:
        result = apply_reviews(store, rebuild_graph=args.rebuild_graph, dry_run=args.dry_run)
        print(
            _json(
                {
                    "output_path": str(result.output_path),
                    "base_concept_count": result.base_concept_count,
                    "merged_candidate_count": result.merged_candidate_count,
                    "total_concept_count": result.total_concept_count,
                    "warnings": result.warnings,
                    "rebuild_graph": args.rebuild_graph,
                    "dry_run": args.dry_run,
                }
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
