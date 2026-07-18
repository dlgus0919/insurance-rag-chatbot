#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ontology.approval_integrity import (
    ActiveManifestAudit,
    ApprovalPatch,
    BaseManifestLock,
    LegacyApprovalUnverifiableError,
    audit_active_manifest,
    build_base_manifest_lock,
)
from src.ontology.manifest_merge import ManifestMergeResult, merge_approved_candidates
from src.ontology.candidate_display import format_candidate_for_practitioner
from src.ontology.candidate_quality import sanitize_candidate_aliases
from src.ontology.hold_feedback import HOLD_REASON_BY_CODE, normalize_hold_reason_codes
from src.ontology.policy import load_review_policy
from src.ontology.registry import (
    ACTIVE_ONTOLOGY_MANIFEST,
    ACTIVE_ONTOLOGY_PROVENANCE,
    BASE_ONTOLOGY_LOCK,
    BASE_ONTOLOGY_MANIFEST,
)
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


@dataclass(frozen=True)
class OntologyReviewApplyResult:
    """One dry-run or applied ontology review result with integrity evidence."""

    status: str
    merge_result: ManifestMergeResult | None
    audit: ActiveManifestAudit | None
    concept_diffs: tuple[dict[str, str], ...]
    legacy_unverifiable_candidate_ids: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.status in {"dry_run", "applied"} and (
            self.audit is not None and self.audit.report.state == "valid"
        )

    def to_dict(self, *, rebuild_graph: bool = False) -> dict[str, Any]:
        merge = self.merge_result
        audit = self.audit
        return {
            "status": self.status,
            "valid": self.valid,
            "trusted_base_content_hash": (
                merge.trusted_base_content_hash if merge is not None else ""
            ),
            "expected_active_content_hash": (
                merge.active_content_hash if merge is not None else ""
            ),
            "applied_operations": [
                operation.to_dict()
                for operation in (audit.approved_operations if audit is not None else ())
            ],
            "quarantined_concept_ids": list(
                audit.report.quarantined_concept_ids if audit is not None else ()
            ),
            "legacy_unverifiable_candidate_ids": list(self.legacy_unverifiable_candidate_ids),
            "concept_diffs": list(self.concept_diffs),
            "graph_rebuild_required": bool(
                rebuild_graph or (merge is not None and merge.applied_operation_count > 0)
            ),
            "warnings": list(merge.warnings if merge is not None else ()),
        }


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


def _print_candidate(candidate: OntologyCandidate, *, candidates: list[OntologyCandidate], wrap_width: int | None) -> None:
    print(
        format_candidate_for_practitioner(
            candidate,
            all_candidates=candidates,
            wrap_width=wrap_width,
        )
    )


def _print_approval_operations(operations: list[dict[str, str]]) -> None:
    if not operations:
        print("\n승인 가능 변경 항목: 없음")
        return
    print("\n승인 가능 변경 항목:")
    for operation in operations:
        print(
            "- "
            f"{operation.get('field_label') or '승인 변경 항목'}: "
            f"{operation.get('value_preview') or '-'}\n"
            f"  path: {operation.get('path') or '-'}\n"
            f"  value_hash: {operation.get('value_hash') or '-'}"
        )


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


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object is required: {path}")
    return payload


def _approval_patches(
    store: OntologyReviewStore,
    candidates: list[OntologyCandidate],
) -> tuple[dict[str, ApprovalPatch], tuple[str, ...]]:
    patches: dict[str, ApprovalPatch] = {}
    legacy_ids: list[str] = []
    for candidate in candidates:
        patch = store.latest_approval_patch(candidate.candidate_id)
        if patch is None:
            legacy_ids.append(candidate.candidate_id)
            continue
        patches[candidate.candidate_id] = patch
    return patches, tuple(sorted(legacy_ids))


def _run_merge_and_audit(
    *,
    candidates: list[OntologyCandidate],
    approval_patches: dict[str, ApprovalPatch],
    base_manifest_path: Path,
    base_lock_path: Path,
    active_manifest_path: Path,
    provenance_path: Path,
) -> tuple[ManifestMergeResult, ActiveManifestAudit]:
    result = merge_approved_candidates(
        candidates,
        approval_patches=approval_patches,
        base_manifest_path=base_manifest_path,
        base_lock_path=base_lock_path,
        output_path=active_manifest_path,
        provenance_path=provenance_path,
    )
    audit = audit_active_manifest(
        _load_json_object(base_manifest_path),
        BaseManifestLock.load(base_lock_path),
        _load_json_object(active_manifest_path),
        _load_json_object(provenance_path),
    )
    return result, audit


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
    base_manifest_path: str | Path = BASE_ONTOLOGY_MANIFEST,
    base_lock_path: str | Path = BASE_ONTOLOGY_LOCK,
    active_manifest_path: str | Path = ACTIVE_ONTOLOGY_MANIFEST,
    provenance_path: str | Path = ACTIVE_ONTOLOGY_PROVENANCE,
) -> OntologyReviewApplyResult:
    candidates = store.approved_or_applied_candidates()
    if not candidates and not dry_run:
        raise ValueError("approved/applied ontology candidates do not exist")

    base_path = Path(base_manifest_path)
    lock_path = Path(base_lock_path)
    active_path = Path(active_manifest_path)
    provenance = Path(provenance_path)
    approval_patches, legacy_ids = _approval_patches(store, candidates)
    if legacy_ids:
        return OntologyReviewApplyResult(
            status="legacy_unverifiable",
            merge_result=None,
            audit=None,
            concept_diffs=(),
            legacy_unverifiable_candidate_ids=legacy_ids,
        )

    with rebuild_lock():
        if dry_run:
            with tempfile.TemporaryDirectory(prefix="ontology-review-dry-run-") as raw_directory:
                directory = Path(raw_directory)
                result, audit = _run_merge_and_audit(
                    candidates=candidates,
                    approval_patches=approval_patches,
                    base_manifest_path=base_path,
                    base_lock_path=lock_path,
                    active_manifest_path=directory / "concepts.active.json",
                    provenance_path=directory / "concepts.active.provenance.json",
                )
            return OntologyReviewApplyResult(
                status="dry_run" if audit.report.state == "valid" else audit.report.state,
                merge_result=result,
                audit=audit,
                concept_diffs=tuple(item.to_dict() for item in audit.concept_diffs),
            )
        active_path.parent.mkdir(parents=True, exist_ok=True)
        provenance.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ontology-review-apply-", dir=active_path.parent) as raw_directory:
            directory = Path(raw_directory)
            staged_active = directory / active_path.name
            staged_provenance = directory / provenance.name
            result, audit = _run_merge_and_audit(
                candidates=candidates,
                approval_patches=approval_patches,
                base_manifest_path=base_path,
                base_lock_path=lock_path,
                active_manifest_path=staged_active,
                provenance_path=staged_provenance,
            )
            if audit.report.state != "valid":
                raise LegacyApprovalUnverifiableError(
                    f"ontology integrity audit failed before apply: {audit.report.state}"
                )
            _validate_active_manifest(staged_active)
            _backup_file(active_path, ONTOLOGY_BACKUP_DIR)
            os.replace(staged_provenance, provenance)
            os.replace(staged_active, active_path)
        if rebuild_graph:
            _rebuild_graph(active_path)
        store.mark_approved_as_applied(
            manifest_path=active_path,
            approval_patches=approval_patches,
            active_content_hash=result.active_content_hash,
        )
        return OntologyReviewApplyResult(
            status="applied",
            merge_result=result,
            audit=audit,
            concept_diffs=tuple(item.to_dict() for item in audit.concept_diffs),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Review and apply ontology candidates.")
    parser.add_argument("--pending-count", action="store_true", help="Print pending candidate count.")
    parser.add_argument("--summary", action="store_true", help="Print review candidate status summary.")
    parser.add_argument("--list-json", action="store_true", help="Print candidates as JSON.")
    parser.add_argument("--list-ids", action="store_true", help="Print candidate ids, one per line.")
    parser.add_argument("--list-zenity", action="store_true", help="Print pending candidates as newline-separated zenity rows.")
    parser.add_argument("--status", choices=["pending", "approved", "held", "rejected", "applied"], default=None)
    parser.add_argument("--show", metavar="CANDIDATE_ID", help="Show a human-readable candidate detail.")
    parser.add_argument("--wrap-width", type=int, default=82, help="Wrap --show output to this character width. Use 0 to disable.")
    parser.add_argument("--seed-test-candidate", action="store_true", help="Create or replace one test-only ontology candidate.")
    parser.add_argument("--decide", metavar="CANDIDATE_ID", help="Candidate id to decide.")
    parser.add_argument("--decision", choices=["approve", "hold", "reject"], help="Decision for --decide.")
    parser.add_argument("--reviewer", default="practitioner", help="Reviewer name for audit log.")
    parser.add_argument("--reviewer-type", default="practitioner", help="Reviewer type for audit log.")
    parser.add_argument("--reason", default="", help="Decision reason.")
    parser.add_argument(
        "--approve-path",
        action="append",
        default=[],
        metavar="JSON_POINTER",
        help="Approval operation path. Repeat for each explicitly approved field.",
    )
    parser.add_argument(
        "--hold-reason-code",
        action="append",
        default=[],
        choices=sorted(HOLD_REASON_BY_CODE),
        help="Structured hold reason code. Can be repeated with --decision hold.",
    )
    parser.add_argument("--auto-approve-test", action="store_true", help="Approve pending test_candidate=true candidates only.")
    parser.add_argument(
        "--sanitize-candidate-aliases",
        action="store_true",
        help="Remove sentence-like or multi-owner candidate aliases from review candidates.",
    )
    parser.add_argument("--review-policy", default=None, help="Ontology review policy JSON path.")
    parser.add_argument("--validate-policy", action="store_true", help="Validate the ontology review policy before running.")
    parser.add_argument(
        "--auto-approve-dev",
        action="store_true",
        help="Approve pending development-only candidates with codex_dev_review approval metadata.",
    )
    parser.add_argument("--apply", action="store_true", help="Generate active manifest from approved/applied candidates.")
    parser.add_argument("--rebuild-graph", action="store_true", help="Rebuild GraphDB after --apply.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned operations without mutating files.")
    parser.add_argument("--build-base-lock", action="store_true", help="Build a deterministic reviewed base lock only.")
    parser.add_argument("--base", default=None, help="Base ontology manifest path for --apply or --build-base-lock.")
    parser.add_argument("--base-lock", default=None, help="Reviewed base lock path for --apply.")
    parser.add_argument("--active-manifest", default=None, help="Active manifest output path for --apply.")
    parser.add_argument("--provenance", default=None, help="Active provenance sidecar path for --apply.")
    parser.add_argument("--source-commit", default=None, help="Reviewed source commit for --build-base-lock.")
    parser.add_argument("--review-record-id", default=None, help="Review record id for --build-base-lock.")
    parser.add_argument("--output", default=None, help="Output path for --build-base-lock.")
    args = parser.parse_args()

    if args.build_base_lock:
        required = {
            "--base": args.base,
            "--source-commit": args.source_commit,
            "--review-record-id": args.review_record_id,
            "--output": args.output,
        }
        missing = [flag for flag, value in required.items() if not value]
        if missing:
            parser.error(f"--build-base-lock requires {' '.join(missing)}")
        base_payload = _load_json_object(Path(args.base))
        lock = build_base_manifest_lock(
            base_payload,
            source_commit=args.source_commit,
            review_record_id=args.review_record_id,
        )
        lock.write(args.output)
        print(_json({"status": "base_lock_built", "output_path": str(args.output), "lock": lock.to_dict()}))
        return 0

    store = OntologyReviewStore()
    review_policy = load_review_policy(args.review_policy) if args.validate_policy or args.auto_approve_dev else None

    if args.validate_policy and review_policy:
        print(
            _json(
                {
                    "review_policy": {
                        "policy_id": review_policy.policy_id,
                        "version": review_policy.version,
                    },
                    "valid": True,
                }
            )
        )

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
        candidate = store.get_candidate(args.show)
        _print_candidate(
            candidate,
            candidates=store.load_candidates(),
            wrap_width=args.wrap_width or None,
        )
        _print_approval_operations(store.available_approval_operations(candidate.candidate_id))

    if args.decide:
        if not args.decision:
            parser.error("--decision is required with --decide")
        if args.approve_path and args.decision != "approve":
            parser.error("--approve-path is only valid with --decision approve")
        if args.dry_run:
            print(_json({"candidate_id": args.decide, "decision": args.decision, "dry_run": True}))
        else:
            candidate = store.decide(
                args.decide,
                args.decision,
                reviewer=args.reviewer,
                reviewer_type=args.reviewer_type,
                reason=args.reason,
                hold_reason_codes=normalize_hold_reason_codes(args.hold_reason_code),
                approved_paths=args.approve_path,
            )
            print(_json({"updated": candidate.to_dict()}))

    if args.auto_approve_test:
        selected = store.auto_approve_test_candidates(reviewer=args.reviewer, dry_run=args.dry_run)
        print(_json({"auto_approved_test_candidates": [candidate.candidate_id for candidate in selected], "dry_run": args.dry_run}))

    if args.sanitize_candidate_aliases:
        sanitized, changes = sanitize_candidate_aliases(store.load_candidates())
        if not args.dry_run:
            store.save_candidates(sanitized)
        print(_json({"sanitized": not args.dry_run, "changed_count": len(changes), "changes": changes}))

    if args.auto_approve_dev:
        selected = store.auto_approve_codex_development_candidates(
            reviewer=args.reviewer,
            dry_run=args.dry_run,
            policy=review_policy,
        )
        print(_json({"auto_approved_dev_candidates": [candidate.candidate_id for candidate in selected], "dry_run": args.dry_run}))

    if args.apply:
        result = apply_reviews(
            store,
            rebuild_graph=args.rebuild_graph,
            dry_run=args.dry_run,
            base_manifest_path=args.base or BASE_ONTOLOGY_MANIFEST,
            base_lock_path=args.base_lock or BASE_ONTOLOGY_LOCK,
            active_manifest_path=args.active_manifest or ACTIVE_ONTOLOGY_MANIFEST,
            provenance_path=args.provenance or ACTIVE_ONTOLOGY_PROVENANCE,
        )
        print(_json(result.to_dict(rebuild_graph=args.rebuild_graph)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
