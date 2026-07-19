"""Build a reviewed ontology baseline without promoting untrusted deltas."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from src.ontology.approval_integrity import (
    BaseManifestLock,
    ManifestIntegrityReport,
    build_trusted_base_projection,
    canonical_json_hash,
    manifest_content_hash,
)
from src.ontology.manifest_merge import merge_approved_candidates

if TYPE_CHECKING:
    from src.ontology.registry import OntologyRegistry


class SafeBaselineError(ValueError):
    """Raised when a raw manifest cannot be reduced to its reviewed baseline."""


_GRAPH_REQUIRED_TABLES = frozenset(
    {
        "graph_nodes",
        "graph_aliases",
        "graph_edges",
        "graph_evidence",
        "graph_node_evidence",
        "graph_edge_evidence",
        "graph_build_manifest",
    }
)
_GRAPH_COUNT_TABLES = {
    "node_count": "graph_nodes",
    "edge_count": "graph_edges",
    "evidence_count": "graph_evidence",
    "alias_count": "graph_aliases",
}
_RUNTIME_ONTOLOGY_ARTIFACTS = (
    "concepts.base.json",
    "base_manifest.lock.json",
    "concepts.active.json",
    "concepts.active.provenance.json",
)


@dataclass(frozen=True)
class SafeBaselineResult:
    baseline_manifest: dict[str, Any]
    pending_correction_artifact: dict[str, Any]
    integrity_report: ManifestIntegrityReport
    excluded_concept_ids: tuple[str, ...]


@dataclass(frozen=True)
class SafeBaselineReleasePaths:
    """Paths for a prepared baseline that is separate from runtime artifacts."""

    release_path: Path
    base_manifest_path: Path
    base_lock_path: Path
    active_manifest_path: Path
    provenance_path: Path
    graph_db_path: Path
    graph_manifest_path: Path
    pending_artifact_path: Path


def _concept_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    concepts = payload.get("concepts")
    if not isinstance(concepts, list):
        raise SafeBaselineError("raw manifest concepts must be a list")

    result: dict[str, dict[str, Any]] = {}
    for concept in concepts:
        if not isinstance(concept, dict):
            raise SafeBaselineError("raw manifest concepts must contain objects")
        concept_id = str(concept.get("concept_id") or "").strip()
        if not concept_id or concept_id in result:
            raise SafeBaselineError("raw manifest concept ids must be unique and non-empty")
        result[concept_id] = concept
    return result


def build_safe_baseline(
    raw_manifest: dict[str, Any],
    base_lock: BaseManifestLock,
) -> SafeBaselineResult:
    """Return a lock-exact baseline and immutable pending copies of excluded rows.

    Only deltas that are absent from the reviewed lock may be isolated. Any
    missing or modified reviewed concept is an integrity failure, not a
    correction candidate.
    """

    raw_concepts = _concept_map(raw_manifest)
    projection, raw_report = build_trusted_base_projection(raw_manifest, base_lock)
    issue_codes = raw_report.issue_counts()
    if raw_report.state == "stale" or set(issue_codes) - {"UNTRUSTED_BASE_CONCEPT"}:
        raise SafeBaselineError("raw manifest does not preserve the reviewed base")

    excluded_ids = tuple(sorted(raw_report.quarantined_concept_ids))
    if any(concept_id not in raw_concepts for concept_id in excluded_ids):
        raise SafeBaselineError("untrusted correction payload is unavailable")

    baseline_projection, baseline_report = build_trusted_base_projection(projection, base_lock)
    if baseline_report.state != "valid" or baseline_report.quarantined_concept_ids:
        raise SafeBaselineError("safe baseline does not match the reviewed base")
    if manifest_content_hash(baseline_projection) != base_lock.manifest_content_hash:
        raise SafeBaselineError("safe baseline content hash does not match the reviewed lock")

    entries = [
        {
            "concept_id": concept_id,
            "content_hash": canonical_json_hash(raw_concepts[concept_id]),
            "status": "pending",
            "concept": deepcopy(raw_concepts[concept_id]),
        }
        for concept_id in excluded_ids
    ]
    pending_artifact = {
        "schema_version": 1,
        "artifact_type": "untrusted_base_correction_bundle",
        "status": "pending",
        "source_manifest_content_hash": manifest_content_hash(raw_manifest),
        "trusted_base_content_hash": base_lock.manifest_content_hash,
        "entries": entries,
    }
    return SafeBaselineResult(
        baseline_manifest=baseline_projection,
        pending_correction_artifact=pending_artifact,
        integrity_report=baseline_report,
        excluded_concept_ids=excluded_ids,
    )


def _write_json_new(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")


def write_safe_baseline_artifacts(
    result: SafeBaselineResult,
    *,
    baseline_path: str | Path,
    pending_artifact_path: str | Path,
) -> None:
    """Write a baseline and pending bundle once; existing artifacts are immutable."""

    target_baseline = Path(baseline_path)
    target_pending = Path(pending_artifact_path)
    if target_baseline.exists() or target_pending.exists():
        raise FileExistsError("safe-baseline artifacts already exist")
    target_baseline.parent.mkdir(parents=True, exist_ok=True)
    target_pending.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_json_new(target_baseline, result.baseline_manifest)
        _write_json_new(target_pending, result.pending_correction_artifact)
    except Exception:
        target_baseline.unlink(missing_ok=True)
        target_pending.unlink(missing_ok=True)
        raise


def _release_paths(release_path: Path) -> SafeBaselineReleasePaths:
    ontology_dir = release_path / "ontology"
    graph_dir = release_path / "graph"
    return SafeBaselineReleasePaths(
        release_path=release_path,
        base_manifest_path=ontology_dir / "concepts.base.json",
        base_lock_path=ontology_dir / "base_manifest.lock.json",
        active_manifest_path=ontology_dir / "concepts.active.json",
        provenance_path=ontology_dir / "concepts.active.provenance.json",
        graph_db_path=graph_dir / "insurance_graph.sqlite",
        graph_manifest_path=graph_dir / "insurance_graph_manifest.json",
        pending_artifact_path=release_path / "pending-corrections.json",
    )


def resolve_safe_baseline_release_paths(
    release_root: str | Path,
    release_id: str,
) -> SafeBaselineReleasePaths:
    """Resolve a versioned release path without inspecting runtime artifacts."""

    normalized_release_id = str(release_id or "").strip()
    if not normalized_release_id or Path(normalized_release_id).name != normalized_release_id:
        raise SafeBaselineError("release id must be a single directory name")
    return _release_paths(Path(release_root).resolve() / normalized_release_id)


def _path_is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _load_graph_manifest(path: Path) -> dict[str, str]:
    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise SafeBaselineError("graph manifest is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise SafeBaselineError("graph manifest must be a JSON object")
    return {str(key): str(value) for key, value in payload.items()}


def _read_graph_database_manifest_and_counts(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Read graph artifacts without creating or modifying a SQLite database."""

    from src.graph.store import GraphStore

    try:
        store = GraphStore(path, readonly=True)
    except (OSError, sqlite3.Error) as exc:
        raise SafeBaselineError("prepared graph database is unreadable") from exc

    try:
        tables = {
            str(row["name"])
            for row in store.query("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        missing_tables = sorted(_GRAPH_REQUIRED_TABLES - tables)
        if missing_tables:
            raise SafeBaselineError(
                "prepared graph database is missing required tables: "
                + ", ".join(missing_tables)
            )
        integrity_rows = store.query("PRAGMA integrity_check")
        if len(integrity_rows) != 1 or str(integrity_rows[0][0]) != "ok":
            raise SafeBaselineError(
                "prepared graph database failed referential integrity validation"
            )
        if store.query("PRAGMA foreign_key_check"):
            raise SafeBaselineError(
                "prepared graph database failed referential integrity validation"
            )
        missing_source_evidence = store.query(
            """
            SELECT graph_edges.edge_id
            FROM graph_edges
            LEFT JOIN graph_evidence
              ON graph_evidence.evidence_id = graph_edges.source_evidence_id
            WHERE graph_edges.source_evidence_id IS NOT NULL
              AND graph_evidence.evidence_id IS NULL
            LIMIT 1
            """
        )
        if missing_source_evidence:
            raise SafeBaselineError(
                "prepared graph database failed referential integrity validation"
            )
        manifest = {
            str(row["key"]): str(row["value"])
            for row in store.query("SELECT key, value FROM graph_build_manifest")
        }
        counts = {
            manifest_key: str(
                store.query(f"SELECT COUNT(*) AS count FROM {table_name}")[0]["count"]
            )
            for manifest_key, table_name in _GRAPH_COUNT_TABLES.items()
        }
    except SafeBaselineError:
        raise
    except (IndexError, KeyError, sqlite3.Error) as exc:
        raise SafeBaselineError("prepared graph database failed integrity validation") from exc
    finally:
        store.close()
    return manifest, counts


def _graph_artifact_errors(
    registry: "OntologyRegistry",
    internal_manifest: dict[str, str],
    external_manifest: dict[str, str],
    actual_counts: dict[str, str],
) -> list[str]:
    errors = registry.graph_manifest_integrity_errors(internal_manifest)
    for key, external_value in external_manifest.items():
        internal_value = internal_manifest.get(key)
        if internal_value is None:
            errors.append(f"{key}: missing from graph database manifest")
        elif internal_value != external_value:
            errors.append(f"{key}: graph database manifest differs from external manifest")
    for manifest_key, actual_count in actual_counts.items():
        for label, manifest in (("external", external_manifest), ("internal", internal_manifest)):
            expected_count = manifest.get(manifest_key)
            if expected_count is None:
                errors.append(f"{manifest_key}: missing from {label} graph manifest")
                continue
            try:
                parsed_count = int(expected_count)
            except ValueError:
                errors.append(f"{manifest_key}: invalid {label} graph manifest count")
                continue
            if parsed_count < 0 or str(parsed_count) != actual_count:
                errors.append(f"{manifest_key}: {label} graph manifest count does not match graph data")
    return errors


def _verify_prepared_release(paths: SafeBaselineReleasePaths) -> "OntologyRegistry":
    from src.ontology.registry import OntologyRegistry

    registry = OntologyRegistry(
        paths.active_manifest_path,
        base_manifest_path=paths.base_manifest_path,
        base_lock_path=paths.base_lock_path,
        provenance_path=paths.provenance_path,
    )
    if registry.integrity_report.state != "valid":
        raise SafeBaselineError("prepared active manifest did not pass integrity validation")
    external_manifest = _load_graph_manifest(paths.graph_manifest_path)
    if registry.graph_manifest_integrity_errors(external_manifest):
        raise SafeBaselineError("graph manifest does not match prepared ontology")
    internal_manifest, actual_counts = _read_graph_database_manifest_and_counts(
        paths.graph_db_path
    )
    graph_errors = _graph_artifact_errors(
        registry,
        internal_manifest,
        external_manifest,
        actual_counts,
    )
    if graph_errors:
        raise SafeBaselineError("graph database does not match prepared ontology")
    return registry


def verify_safe_baseline_release(release: SafeBaselineReleasePaths) -> "OntologyRegistry":
    """Verify a prepared release before an operator-controlled publication."""

    return _verify_prepared_release(release)


def load_safe_baseline_runtime_registry(runtime_root: str | Path) -> "OntologyRegistry":
    """Load only a complete safe-baseline runtime set; never fall back to raw data."""

    paths = _release_paths(Path(runtime_root))
    required = (
        paths.base_manifest_path,
        paths.base_lock_path,
        paths.active_manifest_path,
        paths.provenance_path,
        paths.graph_db_path,
        paths.graph_manifest_path,
    )
    if any(not path.is_file() for path in required):
        raise SafeBaselineError(
            "safe baseline runtime artifacts are unavailable; raw fallback is not allowed"
        )
    return _verify_prepared_release(paths)


def prepare_safe_baseline_release(
    result: SafeBaselineResult,
    *,
    base_lock: BaseManifestLock,
    release_root: str | Path,
    release_id: str,
    runtime_root: str | Path,
    graph_builder: Callable[[SafeBaselineReleasePaths, "OntologyRegistry"], None],
) -> SafeBaselineReleasePaths:
    """Prepare and validate a candidate baseline without touching runtime paths."""

    from src.ontology.registry import OntologyRegistry

    root = Path(release_root).resolve()
    protected_runtime_root = Path(runtime_root).resolve()
    if _path_is_within(root, protected_runtime_root):
        raise SafeBaselineError("release root must be outside the runtime root")
    target_paths = resolve_safe_baseline_release_paths(root, release_id)
    target = target_paths.release_path
    if target.exists():
        raise FileExistsError("safe-baseline release already exists")

    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.prepare-", dir=root))
    paths = _release_paths(staging)
    try:
        paths.graph_db_path.parent.mkdir(parents=True, exist_ok=True)
        write_safe_baseline_artifacts(
            result,
            baseline_path=paths.base_manifest_path,
            pending_artifact_path=paths.pending_artifact_path,
        )
        base_lock.write(paths.base_lock_path)
        merge_approved_candidates(
            [],
            approval_patches={},
            base_manifest_path=paths.base_manifest_path,
            base_lock_path=paths.base_lock_path,
            output_path=paths.active_manifest_path,
            provenance_path=paths.provenance_path,
        )
        registry = OntologyRegistry(
            paths.active_manifest_path,
            base_manifest_path=paths.base_manifest_path,
            base_lock_path=paths.base_lock_path,
            provenance_path=paths.provenance_path,
        )
        if registry.integrity_report.state != "valid":
            raise SafeBaselineError("prepared active manifest did not pass integrity validation")
        graph_builder(paths, registry)
        _verify_prepared_release(paths)
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return _release_paths(target)


def _copy_artifact(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target)
        return
    shutil.copy2(source, target)


def _replace_runtime_artifact(source: Path, target: Path) -> None:
    """Replace one staged runtime artifact, including a non-empty graph directory."""

    if not source.is_dir():
        source.replace(target)
        return
    displaced = source.parent / f".{target.name}.displaced"
    if target.exists():
        target.replace(displaced)
    try:
        source.replace(target)
    except Exception:
        if displaced.exists():
            displaced.replace(target)
        raise
    if displaced.exists():
        shutil.rmtree(displaced)


def _restore_runtime_artifacts(
    *,
    backup_root: Path,
    runtime_root: Path,
    transaction_root: Path,
) -> None:
    restore_root = transaction_root / "restore"
    restore_ontology = restore_root / "ontology"
    restore_graph = restore_root / "graph"
    restore_ontology.mkdir(parents=True)
    for filename in _RUNTIME_ONTOLOGY_ARTIFACTS:
        source = backup_root / "ontology" / filename
        target = runtime_root / "ontology" / filename
        if source.is_file():
            _copy_artifact(source, restore_ontology / filename)
        elif target.exists():
            target.unlink()
    _copy_artifact(backup_root / "graph", restore_graph)
    for filename in _RUNTIME_ONTOLOGY_ARTIFACTS:
        source = restore_ontology / filename
        if source.is_file():
            _replace_runtime_artifact(source, runtime_root / "ontology" / filename)
    _replace_runtime_artifact(restore_graph, runtime_root / "graph")


def _runtime_artifacts_exist(runtime_root: Path) -> bool:
    return (
        (runtime_root / "ontology" / "concepts.active.json").is_file()
        and (runtime_root / "ontology" / "concepts.active.provenance.json").is_file()
        and (runtime_root / "graph").is_dir()
    )


def publish_safe_baseline_release(
    release: SafeBaselineReleasePaths,
    *,
    runtime_root: str | Path,
    operator_acknowledged: bool,
) -> None:
    """Publish a verified release only after an explicit operator acknowledgement."""

    if not operator_acknowledged:
        raise SafeBaselineError("operator acknowledgement is required before publish")
    verify_safe_baseline_release(release)

    root = Path(runtime_root)
    active_target = root / "ontology" / "concepts.active.json"
    provenance_target = root / "ontology" / "concepts.active.provenance.json"
    graph_target = root / "graph"
    if not _runtime_artifacts_exist(root):
        raise SafeBaselineError("runtime artifacts are unavailable for safe publish")

    rollback_root = root / ".safe-baseline-rollback"
    if rollback_root.exists():
        raise SafeBaselineError("a prior safe baseline rollback is still available")

    transaction = Path(tempfile.mkdtemp(prefix=".safe-baseline-publish-", dir=root))
    backup_root = transaction / "backup"
    stage_root = transaction / "stage"
    backup_retained = False
    try:
        (backup_root / "ontology").mkdir(parents=True)
        for filename in _RUNTIME_ONTOLOGY_ARTIFACTS:
            source = root / "ontology" / filename
            if source.is_file():
                _copy_artifact(source, backup_root / "ontology" / filename)
        _copy_artifact(graph_target, backup_root / "graph")
        (stage_root / "ontology").mkdir(parents=True)
        release_ontology = release.release_path / "ontology"
        for filename in _RUNTIME_ONTOLOGY_ARTIFACTS:
            _copy_artifact(
                release_ontology / filename,
                stage_root / "ontology" / filename,
            )
        _copy_artifact(release.graph_db_path.parent, stage_root / "graph")
        for filename in _RUNTIME_ONTOLOGY_ARTIFACTS:
            _replace_runtime_artifact(
                stage_root / "ontology" / filename,
                root / "ontology" / filename,
            )
        _replace_runtime_artifact(stage_root / "graph", graph_target)
        load_safe_baseline_runtime_registry(root)
        backup_root.replace(rollback_root)
        backup_retained = True
    except Exception as exc:
        try:
            if not backup_retained:
                _restore_runtime_artifacts(
                    backup_root=backup_root,
                    runtime_root=root,
                    transaction_root=transaction,
                )
        except Exception as rollback_exc:
            raise SafeBaselineError("safe baseline publish failed and rollback failed") from rollback_exc
        raise SafeBaselineError("safe baseline publish failed; previous artifacts restored") from exc
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


def rollback_safe_baseline_release(
    runtime_root: str | Path,
    *,
    operator_acknowledged: bool,
) -> None:
    """Restore the one runtime snapshot retained by a safe-baseline publish."""

    if not operator_acknowledged:
        raise SafeBaselineError("operator acknowledgement is required before rollback")

    root = Path(runtime_root)
    rollback_root = root / ".safe-baseline-rollback"
    backup_graph = rollback_root / "graph"
    if (
        not (rollback_root / "ontology" / "concepts.active.json").is_file()
        or not (rollback_root / "ontology" / "concepts.active.provenance.json").is_file()
        or not backup_graph.is_dir()
    ):
        raise SafeBaselineError("safe baseline rollback artifacts are unavailable")
    if not _runtime_artifacts_exist(root):
        raise SafeBaselineError("runtime artifacts are unavailable for safe rollback")

    transaction = Path(tempfile.mkdtemp(prefix=".safe-baseline-rollback-", dir=root))
    current_root = transaction / "current"
    stage_root = transaction / "stage"
    try:
        (current_root / "ontology").mkdir(parents=True)
        for filename in _RUNTIME_ONTOLOGY_ARTIFACTS:
            source = root / "ontology" / filename
            if source.is_file():
                _copy_artifact(source, current_root / "ontology" / filename)
        _copy_artifact(root / "graph", current_root / "graph")

        (stage_root / "ontology").mkdir(parents=True)
        for filename in _RUNTIME_ONTOLOGY_ARTIFACTS:
            source = rollback_root / "ontology" / filename
            if source.is_file():
                _copy_artifact(source, stage_root / "ontology" / filename)
        _copy_artifact(backup_graph, stage_root / "graph")
        for filename in _RUNTIME_ONTOLOGY_ARTIFACTS:
            source = stage_root / "ontology" / filename
            target = root / "ontology" / filename
            if source.is_file():
                _replace_runtime_artifact(source, target)
            elif target.exists():
                target.unlink()
        _replace_runtime_artifact(stage_root / "graph", root / "graph")
    except Exception as exc:
        try:
            _restore_runtime_artifacts(
                backup_root=current_root,
                runtime_root=root,
                transaction_root=transaction,
            )
        except Exception as restore_exc:
            raise SafeBaselineError("safe baseline rollback failed and recovery failed") from restore_exc
        raise SafeBaselineError("safe baseline rollback failed; current artifacts restored") from exc
    else:
        shutil.rmtree(rollback_root)
    finally:
        shutil.rmtree(transaction, ignore_errors=True)
