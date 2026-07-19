from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from src.ontology.safe_baseline import SafeBaselineReleasePaths

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_ontology_safe_baseline.py"


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def test_help_lists_all_operator_safe_baseline_actions() -> None:
    result = _run_cli("--help")

    assert result.returncode == 0
    for command in ("prepare", "verify", "publish", "rollback"):
        assert command in result.stdout


def test_publish_requires_explicit_runtime_root_and_confirmation(tmp_path: Path) -> None:
    release_root = tmp_path / "releases"
    missing_runtime_root = _run_cli(
        "publish",
        "--release-root",
        str(release_root),
        "--release-id",
        "candidate-a",
    )

    assert missing_runtime_root.returncode == 2
    assert "publish requires --runtime-root" in missing_runtime_root.stderr

    missing_confirmation = _run_cli(
        "publish",
        "--release-root",
        str(release_root),
        "--release-id",
        "candidate-a",
        "--runtime-root",
        str(tmp_path / "runtime"),
    )

    assert missing_confirmation.returncode == 2
    assert "publish requires --confirm PUBLISH_SAFE_BASELINE" in missing_confirmation.stderr


def test_rollback_requires_explicit_runtime_root_and_confirmation(tmp_path: Path) -> None:
    missing_runtime_root = _run_cli("rollback")

    assert missing_runtime_root.returncode == 2
    assert "rollback requires --runtime-root" in missing_runtime_root.stderr

    missing_confirmation = _run_cli(
        "rollback",
        "--runtime-root",
        str(tmp_path / "runtime"),
    )

    assert missing_confirmation.returncode == 2
    assert "rollback requires --confirm ROLLBACK_SAFE_BASELINE" in missing_confirmation.stderr


def test_graph_builder_uses_prepared_registry_in_strict_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cli = importlib.import_module("scripts.prepare_ontology_safe_baseline")
    captured: dict[str, object] = {}

    class PreparedRegistry:
        def graph_manifest_metadata(self) -> dict[str, str]:
            return {
                "ontology_manifest_content_hash": "manifest-hash",
                "ontology_provenance_content_hash": "provenance-hash",
                "ontology_integrity_state": "valid",
                "ontology_quarantined_concept_count": "0",
            }

    def fake_build_graph(*args: object, **kwargs: object) -> None:
        captured.update(kwargs)
        manifest_path = Path(str(args[3]))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("{}\n", encoding="utf-8")

    from src.graph import build as graph_build

    monkeypatch.setattr(graph_build, "build_graph", fake_build_graph)
    parser = argparse.ArgumentParser()
    document_manifest = tmp_path / "chunks_canonical_manifest.jsonl"
    document_manifest.write_text('{"chunk_id": "chunk-1"}\n', encoding="utf-8")
    args = argparse.Namespace(
        parser=parser,
        chunks_path=str(tmp_path / "chunks.jsonl"),
        standard_db_path=str(tmp_path / "standard_codes.sqlite"),
        canonical_document_manifest_path=str(document_manifest),
        source_mode="v1_v2_combined",
        rule_links_path=None,
        active_source_chunks_path=None,
    )
    release_path = tmp_path / "release"
    paths = SafeBaselineReleasePaths(
        release_path=release_path,
        base_manifest_path=release_path / "ontology" / "concepts.base.json",
        base_lock_path=release_path / "ontology" / "base_manifest.lock.json",
        active_manifest_path=release_path / "ontology" / "concepts.active.json",
        provenance_path=release_path / "ontology" / "concepts.active.provenance.json",
        graph_db_path=release_path / "graph" / "insurance_graph.sqlite",
        graph_manifest_path=release_path / "graph" / "insurance_graph_manifest.json",
        pending_artifact_path=release_path / "pending-corrections.json",
    )
    prepared = PreparedRegistry()

    cli._build_graph_builder(args)(paths, prepared)

    assert captured["ontology_registry"] is prepared
    assert captured["strict"] is True


def test_canonical_document_manifest_rejects_ontology_concepts_json(tmp_path: Path) -> None:
    cli = importlib.import_module("scripts.prepare_ontology_safe_baseline")
    parser = argparse.ArgumentParser()
    concepts_manifest = tmp_path / "concepts.json"
    concepts_manifest.write_text('{"concepts": []}\n', encoding="utf-8")
    args = argparse.Namespace(canonical_document_manifest_path=str(concepts_manifest))

    with pytest.raises(SystemExit) as raised:
        cli._canonical_document_manifest_path(parser, args)

    assert raised.value.code == 2


@pytest.mark.parametrize(
    "trailing_row",
    ["{not valid json}\n", "[]\n"],
    ids=["malformed-json", "non-object"],
)
def test_canonical_document_manifest_rejects_invalid_trailing_rows(
    tmp_path: Path,
    trailing_row: str,
) -> None:
    cli = importlib.import_module("scripts.prepare_ontology_safe_baseline")
    parser = argparse.ArgumentParser()
    document_manifest = tmp_path / "chunks_canonical_manifest.jsonl"
    document_manifest.write_text(
        '{"chunk_id": "chunk-1"}\n' + trailing_row,
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as raised:
        cli._canonical_document_manifest_path(
            parser,
            argparse.Namespace(canonical_document_manifest_path=str(document_manifest)),
        )

    assert raised.value.code == 2


def test_active_source_overlay_rejects_missing_explicit_path(tmp_path: Path) -> None:
    cli = importlib.import_module("scripts.prepare_ontology_safe_baseline")
    parser = argparse.ArgumentParser()
    args = argparse.Namespace(active_source_chunks_path=str(tmp_path / "missing.jsonl"))

    with pytest.raises(SystemExit) as raised:
        cli._active_source_chunks_path(parser, args)

    assert raised.value.code == 2


def test_canonical_document_manifest_forwards_jsonl_to_graph_builder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cli = importlib.import_module("scripts.prepare_ontology_safe_baseline")
    captured: dict[str, object] = {}
    document_manifest = tmp_path / "chunks_canonical_manifest.jsonl"
    document_manifest.write_text('{"chunk_id": "chunk-1"}\n', encoding="utf-8")

    class PreparedRegistry:
        def graph_manifest_metadata(self) -> dict[str, str]:
            return {}

    def fake_build_graph(*args: object, **kwargs: object) -> None:
        captured.update(kwargs)
        manifest_path = Path(str(args[3]))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("{}\n", encoding="utf-8")

    from src.graph import build as graph_build

    monkeypatch.setattr(graph_build, "build_graph", fake_build_graph)
    parser = argparse.ArgumentParser()
    args = argparse.Namespace(
        parser=parser,
        chunks_path=str(tmp_path / "chunks.jsonl"),
        standard_db_path=str(tmp_path / "standard_codes.sqlite"),
        canonical_document_manifest_path=str(document_manifest),
        source_mode="v1_v2_combined",
        rule_links_path=None,
        active_source_chunks_path=None,
    )
    release_path = tmp_path / "release"
    paths = SafeBaselineReleasePaths(
        release_path=release_path,
        base_manifest_path=release_path / "ontology" / "concepts.base.json",
        base_lock_path=release_path / "ontology" / "base_manifest.lock.json",
        active_manifest_path=release_path / "ontology" / "concepts.active.json",
        provenance_path=release_path / "ontology" / "concepts.active.provenance.json",
        graph_db_path=release_path / "graph" / "insurance_graph.sqlite",
        graph_manifest_path=release_path / "graph" / "insurance_graph_manifest.json",
        pending_artifact_path=release_path / "pending-corrections.json",
    )

    cli._build_graph_builder(args)(paths, PreparedRegistry())

    assert captured["canonical_manifest_path"] == str(document_manifest)
