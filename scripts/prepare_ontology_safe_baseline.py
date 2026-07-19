#!/usr/bin/env python3
"""Prepare and operator-control a reviewed ontology safe-baseline release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ontology.approval_integrity import BaseManifestLock
from src.ontology.safe_baseline import (
    SafeBaselineReleasePaths,
    build_safe_baseline,
    graph_source_manifest_metadata,
    prepare_safe_baseline_release,
    publish_safe_baseline_release,
    resolve_safe_baseline_release_paths,
    rollback_safe_baseline_release,
    verify_safe_baseline_release,
    write_safe_baseline_artifacts,
)

PUBLISH_CONFIRMATION = "PUBLISH_SAFE_BASELINE"
ROLLBACK_CONFIRMATION = "ROLLBACK_SAFE_BASELINE"


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("JSON object is required")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require_value(parser: argparse.ArgumentParser, args: argparse.Namespace, name: str) -> str:
    value = str(getattr(args, name, "") or "").strip()
    if not value:
        command = args.command or "legacy"
        parser.error(f"{command} requires --{name.replace('_', '-')}")
    return value


def _require_confirmation(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    expected_token: str,
) -> None:
    if str(args.confirm or "") != expected_token:
        parser.error(f"{args.command} requires --confirm {expected_token}")


def _release_paths(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> SafeBaselineReleasePaths:
    return resolve_safe_baseline_release_paths(
        _require_value(parser, args, "release_root"),
        _require_value(parser, args, "release_id"),
    )


def _canonical_document_manifest_path(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> str | None:
    """Validate the JSONL document manifest consumed by the Graph builder.

    This is intentionally separate from the ontology concepts JSON manifest.
    ``build_graph`` reads one JSON object per line, while ontology manifests are
    a single JSON object and must never be passed through this boundary.
    """

    value = str(getattr(args, "canonical_document_manifest_path", "") or "").strip()
    if not value:
        return None
    path = Path(value)
    if path.suffix != ".jsonl":
        parser.error(
            "prepare requires --canonical-document-manifest-path to reference a JSONL "
            "document manifest, not an ontology concepts JSON manifest"
        )
    if not path.is_file():
        parser.error(f"canonical document manifest does not exist: {path}")
    has_object_row = False
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                parser.error(
                    "canonical document manifest must be JSONL "
                    f"(line {line_number}): {error}"
                )
            if not isinstance(row, dict):
                parser.error(
                    "canonical document manifest rows must be JSON objects "
                    f"(line {line_number})"
                )
            has_object_row = True
    if not has_object_row:
        parser.error("canonical document manifest must contain at least one JSON object row")
    return str(path.resolve())


def _active_source_chunks_path(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> str | None:
    """Validate an explicitly supplied optional source overlay before Graph build."""

    value = str(getattr(args, "active_source_chunks_path", "") or "").strip()
    if not value:
        return None
    path = Path(value)
    if path.suffix != ".jsonl" or not path.is_file():
        parser.error(f"active source overlay does not exist or is not JSONL: {path}")
    return str(path.resolve())


def _build_graph_builder(
    args: argparse.Namespace,
    canonical_document_manifest_path: str | None = None,
):
    chunks_path = _require_value(args.parser, args, "chunks_path")
    standard_db_path = _require_value(args.parser, args, "standard_db_path")
    if canonical_document_manifest_path is None:
        canonical_document_manifest_path = _canonical_document_manifest_path(args.parser, args)
    if canonical_document_manifest_path is None:
        args.parser.error("prepare requires --canonical-document-manifest-path")
    active_source_chunks_path = _active_source_chunks_path(args.parser, args)

    def build_graph_for_release(paths: SafeBaselineReleasePaths, registry) -> None:
        from src.graph.build import build_graph
        from src.graph.store import GraphStore

        build_graph(
            chunks_path,
            standard_db_path,
            paths.graph_db_path,
            paths.graph_manifest_path,
            paths.release_path / "reports" / "graph_low_confidence.jsonl",
            canonical_manifest_path=canonical_document_manifest_path,
            source_mode=args.source_mode,
            rebuild=True,
            rule_links_path=args.rule_links_path or None,
            active_source_chunks_path=active_source_chunks_path,
            ontology_registry=registry,
            strict=True,
        )
        metadata = {
            **registry.graph_manifest_metadata(),
            **graph_source_manifest_metadata(
                canonical_document_manifest_path,
                active_source_chunks_path,
            ),
        }
        store = GraphStore(paths.graph_db_path, build_mode=True)
        try:
            for key, value in metadata.items():
                store.set_manifest(key, value)
            store.commit()
        finally:
            store.close()
        graph_manifest = _load_json_object(paths.graph_manifest_path)
        graph_manifest.update(metadata)
        _write_json(paths.graph_manifest_path, graph_manifest)

    return build_graph_for_release


def _legacy_create(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    result = build_safe_baseline(
        _load_json_object(Path(_require_value(parser, args, "raw_base"))),
        BaseManifestLock.load(_require_value(parser, args, "base_lock")),
    )
    write_safe_baseline_artifacts(
        result,
        baseline_path=_require_value(parser, args, "output_base"),
        pending_artifact_path=_require_value(parser, args, "pending_artifact"),
    )
    print(
        json.dumps(
            {
                "state": result.integrity_report.state,
                "trusted_concept_count": len(result.baseline_manifest["concepts"]),
                "pending_correction_count": len(result.excluded_concept_ids),
                "pending_correction_ids": list(result.excluded_concept_ids),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _prepare_release(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    raw_base = _load_json_object(Path(_require_value(parser, args, "raw_base")))
    base_lock = BaseManifestLock.load(_require_value(parser, args, "base_lock"))
    canonical_document_manifest_path = _canonical_document_manifest_path(parser, args)
    release = prepare_safe_baseline_release(
        build_safe_baseline(raw_base, base_lock),
        base_lock=base_lock,
        release_root=_require_value(parser, args, "release_root"),
        release_id=_require_value(parser, args, "release_id"),
        runtime_root=_require_value(parser, args, "runtime_root"),
        graph_builder=_build_graph_builder(args, canonical_document_manifest_path),
    )
    print(
        json.dumps(
            {
                "state": "prepared",
                "release_id": release.release_path.name,
                "release_path": str(release.release_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _verify_release(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    release = _release_paths(parser, args)
    registry = verify_safe_baseline_release(release)
    print(
        json.dumps(
            {
                "state": "verified",
                "release_id": release.release_path.name,
                "trusted_concept_count": len(registry.concepts),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _publish_release(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    runtime_root = _require_value(parser, args, "runtime_root")
    _require_confirmation(parser, args, PUBLISH_CONFIRMATION)
    release = _release_paths(parser, args)
    publish_safe_baseline_release(
        release,
        runtime_root=runtime_root,
        operator_acknowledged=True,
    )
    print(json.dumps({"state": "published", "release_id": release.release_path.name}))
    return 0


def _rollback_release(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    runtime_root = _require_value(parser, args, "runtime_root")
    _require_confirmation(parser, args, ROLLBACK_CONFIRMATION)
    rollback_safe_baseline_release(runtime_root, operator_acknowledged=True)
    print(json.dumps({"state": "rolled_back"}))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and operator-control a reviewed ontology safe-baseline release."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("prepare", "verify", "publish", "rollback"),
        help="operator action; omit for the legacy artifact-only create mode",
    )
    parser.add_argument("--raw-base")
    parser.add_argument("--base-lock")
    parser.add_argument("--output-base")
    parser.add_argument("--pending-artifact")
    parser.add_argument("--release-root")
    parser.add_argument("--release-id")
    parser.add_argument("--runtime-root")
    parser.add_argument("--confirm")
    parser.add_argument("--chunks-path")
    parser.add_argument("--standard-db-path")
    parser.add_argument(
        "--canonical-document-manifest-path",
        "--canonical-manifest-path",
        dest="canonical_document_manifest_path",
        help="JSONL document manifest consumed by the Graph builder",
    )
    parser.add_argument("--active-source-chunks-path")
    parser.add_argument("--rule-links-path")
    parser.add_argument("--source-mode", default="v1_v2_combined")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.parser = parser
    if args.command is None:
        return _legacy_create(parser, args)
    if args.command == "prepare":
        return _prepare_release(parser, args)
    if args.command == "verify":
        return _verify_release(parser, args)
    if args.command == "publish":
        return _publish_release(parser, args)
    return _rollback_release(parser, args)


if __name__ == "__main__":
    raise SystemExit(main())
