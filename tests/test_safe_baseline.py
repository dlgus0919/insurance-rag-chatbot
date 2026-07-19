from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src import config
import src.ontology.safe_baseline as safe_baseline
import src.ontology.registry as ontology_registry
from src.rag import pipeline as rag_pipeline
from src.ontology.approval_integrity import (
    BaseManifestLock,
    audit_active_manifest,
    canonical_json_hash,
)
from src.ontology.manifest_merge import merge_approved_candidates
from src.graph.schema import Alias, Edge, EdgeType, Evidence, Node, NodeType
from src.graph.store import GraphStore
from src.ontology.safe_baseline import (
    SafeBaselineError,
    build_safe_baseline,
    write_safe_baseline_artifacts,
)


def _manifest(*, include_untrusted: bool = True) -> dict[str, object]:
    concepts: list[dict[str, object]] = [
        {
            "concept_id": "cond.trusted",
            "canonical_name": "검증된 조건",
        }
    ]
    if include_untrusted:
        concepts.append(
            {
                "concept_id": "cond.untrusted",
                "canonical_name": "미승인 조건",
                "aliases": ["검토 대상 표현"],
            }
        )
    return {
        "schema_version": "1.0",
        "version": "baseline-test",
        "description": "safe baseline test manifest",
        "concepts": concepts,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_safe_baseline_excludes_untrusted_payloads_without_approving_them() -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )

    result = build_safe_baseline(_manifest(), lock)

    assert result.integrity_report.state == "valid"
    assert result.integrity_report.quarantined_concept_ids == ()
    assert [concept["concept_id"] for concept in result.baseline_manifest["concepts"]] == [
        "cond.trusted"
    ]
    assert result.excluded_concept_ids == ("cond.untrusted",)
    assert result.pending_correction_artifact["status"] == "pending"
    assert result.pending_correction_artifact["artifact_type"] == "untrusted_base_correction_bundle"
    entry = result.pending_correction_artifact["entries"][0]
    assert entry["concept_id"] == "cond.untrusted"
    assert entry["concept"] == _manifest()["concepts"][1]
    assert entry["content_hash"] == canonical_json_hash(entry["concept"])


def test_safe_baseline_rejects_any_locked_concept_drift() -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    drifted = _manifest(include_untrusted=False)
    drifted["concepts"][0]["canonical_name"] = "변경된 조건"

    with pytest.raises(SafeBaselineError, match="reviewed base"):
        build_safe_baseline(drifted, lock)


def test_safe_baseline_generates_valid_temp_active_and_preserves_pending_bundle(
    tmp_path: Path,
) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    lock_path = tmp_path / "base_manifest.lock.json"
    lock.write(lock_path)

    result = build_safe_baseline(_manifest(), lock)
    baseline_path = tmp_path / "concepts.safe.json"
    pending_path = tmp_path / "pending-corrections.json"
    write_safe_baseline_artifacts(
        result,
        baseline_path=baseline_path,
        pending_artifact_path=pending_path,
    )

    active_path = tmp_path / "concepts.active.json"
    provenance_path = tmp_path / "concepts.active.provenance.json"
    merge_approved_candidates(
        [],
        approval_patches={},
        base_manifest_path=baseline_path,
        base_lock_path=lock_path,
        output_path=active_path,
        provenance_path=provenance_path,
    )

    audit = audit_active_manifest(
        json.loads(baseline_path.read_text(encoding="utf-8")),
        BaseManifestLock.load(lock_path),
        json.loads(active_path.read_text(encoding="utf-8")),
        json.loads(provenance_path.read_text(encoding="utf-8")),
    )
    pending = json.loads(pending_path.read_text(encoding="utf-8"))

    assert audit.report.state == "valid"
    assert audit.report.quarantined_concept_ids == ()
    assert audit.approved_operations == ()
    assert pending["status"] == "pending"
    assert pending["entries"][0]["concept_id"] == "cond.untrusted"


def test_pending_correction_bundle_is_immutable_by_default(tmp_path: Path) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    result = build_safe_baseline(_manifest(), lock)
    baseline_path = tmp_path / "concepts.safe.json"
    pending_path = tmp_path / "pending-corrections.json"
    write_safe_baseline_artifacts(
        result,
        baseline_path=baseline_path,
        pending_artifact_path=pending_path,
    )

    with pytest.raises(FileExistsError):
        write_safe_baseline_artifacts(
            result,
            baseline_path=tmp_path / "second-safe.json",
            pending_artifact_path=pending_path,
        )


def _write_previous_runtime_artifacts(runtime_root: Path) -> dict[Path, bytes]:
    ontology_dir = runtime_root / "ontology"
    graph_dir = runtime_root / "graph"
    ontology_dir.mkdir(parents=True)
    graph_dir.mkdir(parents=True)
    _write_json(
        ontology_dir / "concepts.active.json",
        {"schema_version": "1.0", "version": "previous", "concepts": []},
    )
    _write_json(
        ontology_dir / "concepts.active.provenance.json",
        {"schema_version": 1, "release": "previous"},
    )
    (graph_dir / "insurance_graph.sqlite").write_bytes(b"previous graph database")
    _write_json(graph_dir / "insurance_graph_manifest.json", {"release": "previous"})
    return {
        path: path.read_bytes()
        for path in (
            ontology_dir / "concepts.active.json",
            ontology_dir / "concepts.active.provenance.json",
            graph_dir / "insurance_graph.sqlite",
            graph_dir / "insurance_graph_manifest.json",
        )
    }


def test_prepare_validation_failure_preserves_existing_runtime_artifacts(tmp_path: Path) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    result = build_safe_baseline(_manifest(), lock)
    runtime_root = tmp_path / "runtime"
    before = _write_previous_runtime_artifacts(runtime_root)

    def invalid_graph_builder(paths, _registry) -> None:
        _write_json(paths.graph_manifest_path, {})

    with pytest.raises(SafeBaselineError, match="graph manifest"):
        safe_baseline.prepare_safe_baseline_release(
            result,
            base_lock=lock,
            release_root=tmp_path / "releases",
            release_id="candidate-a",
            runtime_root=runtime_root,
            graph_builder=invalid_graph_builder,
        )

    assert {
        path: path.read_bytes()
        for path in before
    } == before


def _write_valid_graph(paths, registry) -> None:
    manifest = {
        **registry.graph_manifest_metadata(),
        "node_count": "0",
        "edge_count": "0",
        "evidence_count": "0",
        "alias_count": "0",
    }
    store = GraphStore(paths.graph_db_path, build_mode=True)
    for key, value in manifest.items():
        store.set_manifest(key, value)
    store.commit()
    store.close()
    _write_json(paths.graph_manifest_path, manifest)


def _write_graph_with_references(paths, registry) -> None:
    store = GraphStore(paths.graph_db_path, build_mode=True)
    store.upsert_node(
        Node(
            node_id="node:source",
            node_type=NodeType.DecisionConcept,
            canonical_name="source",
            normalized_name="source",
        )
    )
    store.upsert_node(
        Node(
            node_id="node:target",
            node_type=NodeType.DecisionConcept,
            canonical_name="target",
            normalized_name="target",
        )
    )
    store.upsert_node(
        Node(
            node_id="node:alias",
            node_type=NodeType.DecisionConcept,
            canonical_name="alias",
            normalized_name="alias",
        )
    )
    store.upsert_evidence(Evidence(evidence_id="evidence:source"))
    store.upsert_evidence(Evidence(evidence_id="evidence:node"))
    store.upsert_evidence(Evidence(evidence_id="evidence:edge"))
    store.upsert_edge(
        Edge(
            edge_id="edge:primary",
            source_node_id="node:source",
            target_node_id="node:target",
            edge_type=EdgeType.HAS_DECISION,
            source_evidence_id="evidence:source",
        )
    )
    store.add_alias(
        Alias(
            alias_id="alias:primary",
            node_id="node:alias",
            alias="alias",
            normalized_alias="alias",
            source="test",
        )
    )
    store.link_node_evidence("node:source", "evidence:node", "supports")
    store.link_edge_evidence("edge:primary", "evidence:edge", "supports")
    store.commit()
    manifest = {
        **registry.graph_manifest_metadata(),
        **{
            manifest_key: str(
                store.query(f"SELECT COUNT(*) AS count FROM {table_name}")[0]["count"]
            )
            for manifest_key, table_name in safe_baseline._GRAPH_COUNT_TABLES.items()
        },
    }
    for key, value in manifest.items():
        store.set_manifest(key, value)
    store.commit()
    store.close()
    _write_json(paths.graph_manifest_path, manifest)


def _prepare_release_with_references(
    tmp_path: Path,
) -> tuple[safe_baseline.SafeBaselineReleasePaths, Path, dict[Path, bytes]]:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    runtime_root = tmp_path / "runtime"
    before = _write_previous_runtime_artifacts(runtime_root)
    release = safe_baseline.prepare_safe_baseline_release(
        build_safe_baseline(_manifest(), lock),
        base_lock=lock,
        release_root=tmp_path / "releases",
        release_id="candidate-a",
        runtime_root=runtime_root,
        graph_builder=_write_graph_with_references,
    )
    assert safe_baseline.verify_safe_baseline_release(release).integrity_report.state == "valid"
    return release, runtime_root, before


def _delete_graph_reference(
    release: safe_baseline.SafeBaselineReleasePaths,
    statement: str,
    params: tuple[str, ...],
) -> None:
    connection = sqlite3.connect(release.graph_db_path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(statement, params)
        counts = {
            manifest_key: str(
                connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            )
            for manifest_key, table_name in safe_baseline._GRAPH_COUNT_TABLES.items()
        }
        connection.executemany(
            "UPDATE graph_build_manifest SET value = ? WHERE key = ?",
            [(value, key) for key, value in counts.items()],
        )
        connection.commit()
    finally:
        connection.close()
    external_manifest = json.loads(release.graph_manifest_path.read_text(encoding="utf-8"))
    external_manifest.update(counts)
    _write_json(release.graph_manifest_path, external_manifest)


def test_verify_and_publish_reject_orphan_graph_edge_without_runtime_change(
    tmp_path: Path,
) -> None:
    release, _runtime_root, before = _prepare_release_with_references(tmp_path)
    _delete_graph_reference(
        release,
        "DELETE FROM graph_nodes WHERE node_id = ?",
        ("node:target",),
    )

    with pytest.raises(SafeBaselineError, match="referential integrity"):
        safe_baseline.verify_safe_baseline_release(release)
    with pytest.raises(SafeBaselineError, match="referential integrity"):
        safe_baseline.publish_safe_baseline_release(
            release,
            runtime_root=_runtime_root,
            operator_acknowledged=True,
        )

    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize(
    ("statement", "params"),
    [
        ("DELETE FROM graph_nodes WHERE node_id = ?", ("node:alias",)),
        ("DELETE FROM graph_evidence WHERE evidence_id = ?", ("evidence:node",)),
        ("DELETE FROM graph_edges WHERE edge_id = ?", ("edge:primary",)),
        ("DELETE FROM graph_evidence WHERE evidence_id = ?", ("evidence:source",)),
    ],
    ids=["alias", "node-evidence", "edge-evidence", "source-evidence"],
)
def test_verify_rejects_missing_graph_references(
    tmp_path: Path,
    statement: str,
    params: tuple[str, ...],
) -> None:
    release, _runtime_root, _before = _prepare_release_with_references(tmp_path)
    _delete_graph_reference(release, statement, params)

    with pytest.raises(SafeBaselineError, match="referential integrity"):
        safe_baseline.verify_safe_baseline_release(release)


def test_verify_rejects_non_ok_graph_integrity_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, _runtime_root, _before = _prepare_release_with_references(tmp_path)
    original_query = GraphStore.query

    def report_corruption(self, sql: str, params: tuple = ()):
        if sql == "PRAGMA integrity_check":
            return [("not ok",)]
        return original_query(self, sql, params)

    monkeypatch.setattr(GraphStore, "query", report_corruption)

    with pytest.raises(SafeBaselineError, match="referential integrity"):
        safe_baseline.verify_safe_baseline_release(release)


def test_verify_rejects_a_corrupt_prepared_graph_database(tmp_path: Path) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    runtime_root = tmp_path / "runtime"
    _write_previous_runtime_artifacts(runtime_root)
    release = safe_baseline.prepare_safe_baseline_release(
        build_safe_baseline(_manifest(), lock),
        base_lock=lock,
        release_root=tmp_path / "releases",
        release_id="candidate-a",
        runtime_root=runtime_root,
        graph_builder=_write_valid_graph,
    )
    release.graph_db_path.write_bytes(b"not-a-sqlite-graph")

    with pytest.raises(SafeBaselineError, match="graph database"):
        safe_baseline.verify_safe_baseline_release(release)


def test_verify_rejects_internal_external_graph_manifest_mismatch(tmp_path: Path) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    runtime_root = tmp_path / "runtime"
    _write_previous_runtime_artifacts(runtime_root)
    release = safe_baseline.prepare_safe_baseline_release(
        build_safe_baseline(_manifest(), lock),
        base_lock=lock,
        release_root=tmp_path / "releases",
        release_id="candidate-a",
        runtime_root=runtime_root,
        graph_builder=_write_valid_graph,
    )
    external_manifest = json.loads(release.graph_manifest_path.read_text(encoding="utf-8"))
    external_manifest["node_count"] = "1"
    _write_json(release.graph_manifest_path, external_manifest)

    with pytest.raises(SafeBaselineError, match="graph database"):
        safe_baseline.verify_safe_baseline_release(release)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ontology_manifest_content_hash", "mismatched-hash"),
        ("ontology_integrity_state", "quarantined"),
    ],
)
def test_verify_rejects_internal_graph_metadata_mismatch(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    runtime_root = tmp_path / "runtime"
    _write_previous_runtime_artifacts(runtime_root)
    release = safe_baseline.prepare_safe_baseline_release(
        build_safe_baseline(_manifest(), lock),
        base_lock=lock,
        release_root=tmp_path / "releases",
        release_id="candidate-a",
        runtime_root=runtime_root,
        graph_builder=_write_valid_graph,
    )
    connection = sqlite3.connect(release.graph_db_path)
    try:
        connection.execute(
            "UPDATE graph_build_manifest SET value = ? WHERE key = ?",
            (value, key),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SafeBaselineError, match="graph database"):
        safe_baseline.verify_safe_baseline_release(release)


def test_verify_rejects_graph_database_with_missing_required_table(tmp_path: Path) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    runtime_root = tmp_path / "runtime"
    _write_previous_runtime_artifacts(runtime_root)
    release = safe_baseline.prepare_safe_baseline_release(
        build_safe_baseline(_manifest(), lock),
        base_lock=lock,
        release_root=tmp_path / "releases",
        release_id="candidate-a",
        runtime_root=runtime_root,
        graph_builder=_write_valid_graph,
    )
    connection = sqlite3.connect(release.graph_db_path)
    try:
        connection.execute("DROP TABLE graph_edges")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SafeBaselineError, match="missing required tables"):
        safe_baseline.verify_safe_baseline_release(release)


def test_publish_second_swap_failure_restores_all_runtime_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    runtime_root = tmp_path / "runtime"
    before = _write_previous_runtime_artifacts(runtime_root)
    release = safe_baseline.prepare_safe_baseline_release(
        build_safe_baseline(_manifest(), lock),
        base_lock=lock,
        release_root=tmp_path / "releases",
        release_id="candidate-a",
        runtime_root=runtime_root,
        graph_builder=_write_valid_graph,
    )

    original_replace = getattr(safe_baseline, "_replace_runtime_artifact", None)
    swap_count = 0

    def fail_second_swap(source: Path, target: Path) -> None:
        nonlocal swap_count
        swap_count += 1
        if swap_count == 2:
            raise OSError("injected second swap failure")
        assert original_replace is not None
        original_replace(source, target)

    monkeypatch.setattr(
        safe_baseline,
        "_replace_runtime_artifact",
        fail_second_swap,
        raising=False,
    )

    with pytest.raises(SafeBaselineError, match="publish"):
        safe_baseline.publish_safe_baseline_release(
            release,
            runtime_root=runtime_root,
            operator_acknowledged=True,
        )

    assert swap_count >= 2
    assert {path: path.read_bytes() for path in before} == before


def test_safe_runtime_rejects_raw_quarantine_fallback(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    raw_manifest_path = runtime_root / "ontology" / "concepts.json"
    raw_manifest_path.parent.mkdir(parents=True)
    _write_json(raw_manifest_path, _manifest())

    with pytest.raises(SafeBaselineError, match="raw fallback"):
        safe_baseline.load_safe_baseline_runtime_registry(runtime_root)


def test_publish_and_explicit_rollback_restore_saved_runtime_artifacts(tmp_path: Path) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    runtime_root = tmp_path / "runtime"
    before = _write_previous_runtime_artifacts(runtime_root)
    release = safe_baseline.prepare_safe_baseline_release(
        build_safe_baseline(_manifest(), lock),
        base_lock=lock,
        release_root=tmp_path / "releases",
        release_id="candidate-a",
        runtime_root=runtime_root,
        graph_builder=_write_valid_graph,
    )

    safe_baseline.publish_safe_baseline_release(
        release,
        runtime_root=runtime_root,
        operator_acknowledged=True,
    )
    assert (runtime_root / "ontology" / "concepts.active.json").read_bytes() != before[
        runtime_root / "ontology" / "concepts.active.json"
    ]

    safe_baseline.rollback_safe_baseline_release(
        runtime_root,
        operator_acknowledged=True,
    )

    assert {path: path.read_bytes() for path in before} == before


def test_published_safe_runtime_root_is_used_by_default_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    reviewed_base["concepts"][0]["retrieval"] = {
        "expansion_rules": [
            {
                "match_any": ["검증 표현"],
                "expansion_terms": ["안전 런타임 보강"],
            }
        ]
    }
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    runtime_root = tmp_path / "runtime"
    _write_previous_runtime_artifacts(runtime_root)
    release = safe_baseline.prepare_safe_baseline_release(
        build_safe_baseline(reviewed_base, lock),
        base_lock=lock,
        release_root=tmp_path / "releases",
        release_id="candidate-a",
        runtime_root=runtime_root,
        graph_builder=_write_valid_graph,
    )

    safe_baseline.publish_safe_baseline_release(
        release,
        runtime_root=runtime_root,
        operator_acknowledged=True,
    )
    assert (runtime_root / "ontology" / "concepts.base.json").is_file()
    assert (runtime_root / "ontology" / "base_manifest.lock.json").is_file()

    monkeypatch.setenv("INSURANCE_SAFE_BASELINE_RUNTIME_ROOT", str(runtime_root))
    ontology_registry.get_default_ontology_registry.cache_clear()
    try:
        registry = ontology_registry.get_default_ontology_registry()
    finally:
        ontology_registry.get_default_ontology_registry.cache_clear()

    assert registry.integrity_report.state == "valid"
    assert [concept.concept_id for concept in registry.concepts] == ["cond.trusted"]
    assert registry.approved_decision_profile_payloads() == []
    assert config.resolve_graph_index_path() == runtime_root / "graph" / "insurance_graph.sqlite"

    captured_graph_paths: list[Path] = []

    class CapturingGraphRetriever:
        def __init__(self, path: Path) -> None:
            captured_graph_paths.append(path)

    monkeypatch.setattr(rag_pipeline, "GraphRetriever", CapturingGraphRetriever)
    monkeypatch.setattr(rag_pipeline, "_GRAPH_IMPORT_OK", True)
    monkeypatch.setattr(config, "GRAPH_ENABLED", True)
    rag_pipeline.RagPipeline(
        embedder=object(),
        vector_store=object(),
        bm25=object(),
        llm=object(),
        reranker_enabled=False,
        table_store=object(),
    )

    try:
        assert "안전 런타임 보강" in rag_pipeline._expand_retrieval_query("검증 표현")
    finally:
        ontology_registry.get_default_ontology_registry.cache_clear()
    assert captured_graph_paths == [runtime_root / "graph" / "insurance_graph.sqlite"]


def test_configured_safe_runtime_root_rejects_raw_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    (runtime_root / "ontology").mkdir(parents=True)
    _write_json(runtime_root / "ontology" / "concepts.json", _manifest())

    monkeypatch.setenv("INSURANCE_SAFE_BASELINE_RUNTIME_ROOT", str(runtime_root))
    ontology_registry.get_default_ontology_registry.cache_clear()
    try:
        with pytest.raises(SafeBaselineError, match="raw fallback"):
            ontology_registry.get_default_ontology_registry()
    finally:
        ontology_registry.get_default_ontology_registry.cache_clear()


def test_configured_safe_runtime_root_rejects_corrupt_graph_before_rag_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_base = _manifest(include_untrusted=False)
    lock = BaseManifestLock.from_manifest(
        reviewed_base,
        source_commit="trusted-commit",
        review_record_id="review-record",
    )
    runtime_root = tmp_path / "runtime"
    _write_previous_runtime_artifacts(runtime_root)
    release = safe_baseline.prepare_safe_baseline_release(
        build_safe_baseline(_manifest(), lock),
        base_lock=lock,
        release_root=tmp_path / "releases",
        release_id="candidate-a",
        runtime_root=runtime_root,
        graph_builder=_write_valid_graph,
    )
    safe_baseline.publish_safe_baseline_release(
        release,
        runtime_root=runtime_root,
        operator_acknowledged=True,
    )
    (runtime_root / "graph" / "insurance_graph.sqlite").write_bytes(b"corrupt")

    monkeypatch.setenv("INSURANCE_SAFE_BASELINE_RUNTIME_ROOT", str(runtime_root))
    ontology_registry.get_default_ontology_registry.cache_clear()
    try:
        with pytest.raises(SafeBaselineError, match="graph database"):
            rag_pipeline.RagPipeline(
                embedder=object(),
                vector_store=object(),
                bm25=object(),
                llm=object(),
                reranker_enabled=False,
                table_store=object(),
            )
    finally:
        ontology_registry.get_default_ontology_registry.cache_clear()
