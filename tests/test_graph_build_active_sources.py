from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from pathlib import Path
from typing import Any

import pytest

import src.graph.build as graph_build
from src.graph.extractors import PolicyReviewExtractor
from src.graph.store import GraphStore
from src.ontology.approval_integrity import BaseManifestLock, manifest_content_hash
from src.ontology.registry import OntologyRegistry
from src.parser.chunker import Chunk, load_chunks, save_chunks


class _FakeStore:
    def __init__(self, *_args, **_kwargs) -> None:
        self.manifest: dict[str, str] = {}

    def query(self, _sql: str) -> list[dict[str, int]]:
        return [{"count": 0}]

    def set_manifest(self, key: str, value: str) -> None:
        self.manifest[key] = value

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None

    @contextlib.contextmanager
    def transaction(self):
        yield


class _FakeExtractor:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def extract(self, *_args, **_kwargs) -> None:
        return None


class _ValidRegistry:
    version = "verified-test"
    integrity_report = SimpleNamespace(
        state="valid",
        manifest_content_hash="ontology-hash",
        quarantined_concept_ids=(),
    )
    provenance_content_hash = "provenance-hash"

    def graph_manifest_metadata(self) -> dict[str, str]:
        return {
            "ontology_manifest_content_hash": "ontology-hash",
            "ontology_provenance_content_hash": "provenance-hash",
            "ontology_integrity_state": "valid",
            "ontology_quarantined_concept_count": "0",
        }


def _registry_with_one_valid_and_one_quarantined(tmp_path: Path) -> OntologyRegistry:
    base = {
        "schema_version": "1.0",
        "version": "base",
        "concepts": [
            {
                "concept_id": "cond.valid",
                "canonical_name": "검증 개념",
                "node_type": "ClaimCondition",
                "aliases": ["검증 표현"],
            }
        ],
    }
    base_path = tmp_path / "concepts.json"
    base_path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    lock_path = tmp_path / "base.lock.json"
    lock = BaseManifestLock.from_manifest(base, source_commit="test", review_record_id="test")
    lock.write(lock_path)
    active = {
        **base,
        "version": "active",
        "concepts": [
            *base["concepts"],
            {
                "concept_id": "cond.quarantined",
                "canonical_name": "격리 개념",
                "node_type": "ClaimCondition",
                "aliases": ["격리 표현"],
            },
        ],
    }
    active_path = tmp_path / "concepts.active.json"
    active_path.write_text(json.dumps(active, ensure_ascii=False), encoding="utf-8")
    provenance_path = tmp_path / "concepts.active.provenance.json"
    provenance_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-07-18T00:00:00+00:00",
                "active_content_hash": manifest_content_hash(active),
                "trusted_base_content_hash": lock.manifest_content_hash,
                "base_lock": lock.to_dict(),
                "quarantined_concept_ids": [],
                "integrity_issues": [],
                "applied_operations": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return OntologyRegistry(
        active_path,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        provenance_path=provenance_path,
    )


def test_build_graph_merges_active_source_overlay_from_canonical_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest_path = tmp_path / "canonical.jsonl"
    manifest_path.write_text(
        json.dumps(
            {
                "canonical_chunk_id": "canon-001",
                "doc_short": "기존약관",
                "doc_name": "기존 약관",
                "pdf_filename": "old.pdf",
                "page_start": 1,
                "page_end": 1,
                "source_variants": {
                    "v2_only": {
                        "available": True,
                        "variant_chunk_id": "canon-001-v2",
                        "text": "기존 약관 본문",
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    active_chunks_path = tmp_path / "active" / "chunks.jsonl"
    save_chunks(
        [
            Chunk(
                id="intake:intake-001:0001",
                text="신규 약관 본문",
                metadata={"source_status": "active_intake_source"},
            )
        ],
        active_chunks_path,
    )

    saved_chunk_ids: list[list[str]] = []
    original_save_chunks = graph_build.save_chunks

    def capture_save_chunks(chunks: list[Chunk], path: Path) -> None:
        chunk_list = list(chunks)
        saved_chunk_ids.append([chunk.id for chunk in chunk_list])
        original_save_chunks(chunk_list, path)

    monkeypatch.setattr(graph_build, "GraphStore", _FakeStore)
    monkeypatch.setattr(graph_build, "save_chunks", capture_save_chunks)
    for name in (
        "SurgeryGradeExtractor",
        "PolicyAppendixExtractor",
        "HiraCodeExtractor",
        "NonpayStandardExtractor",
        "PolicyReviewExtractor",
    ):
        monkeypatch.setattr(graph_build, name, _FakeExtractor)
    monkeypatch.setattr(graph_build, "SilsonCoverageExtractor", _FakeExtractor)
    monkeypatch.setattr(graph_build, "_build_cross_references", lambda _store: None)

    graph_build.build_graph(
        chunks_path=tmp_path / "unused_chunks.jsonl",
        standard_db_path=tmp_path / "standard.sqlite",
        output_db_path=tmp_path / "graph.sqlite",
        manifest_path=tmp_path / "graph_manifest.json",
        low_confidence_report_path=tmp_path / "low_confidence.jsonl",
        canonical_manifest_path=manifest_path,
        active_source_chunks_path=active_chunks_path,
        source_mode="v2_only",
        rebuild=True,
        skip_standard_codes=True,
        skip_policy_appendix=True,
        skip_hira_codes=True,
        rule_links_path=None,
        ontology_registry=_ValidRegistry(),
    )

    assert saved_chunk_ids[0] == ["canon-001-v2", "intake:intake-001:0001"]
    manifest = json.loads((tmp_path / "graph_manifest.json").read_text(encoding="utf-8"))
    assert manifest["active_source_chunks_path"] == str(active_chunks_path)
    assert manifest["ontology_manifest_content_hash"] == "ontology-hash"
    assert manifest["ontology_provenance_content_hash"] == "provenance-hash"
    assert manifest["ontology_integrity_state"] == "valid"
    assert manifest["ontology_quarantined_concept_count"] == "0"


def test_build_graph_merges_active_source_overlay_from_fallback_chunks(tmp_path: Path) -> None:
    base_chunks = [Chunk(id="base-001", text="기존 본문", metadata={})]
    active_chunks = [Chunk(id="intake:intake-001:0001", text="신규 본문", metadata={})]
    active_path = tmp_path / "active" / "chunks.jsonl"
    save_chunks(active_chunks, active_path)

    merged = graph_build._merge_active_source_chunks(base_chunks, active_path)

    assert [chunk.id for chunk in merged] == ["base-001", "intake:intake-001:0001"]
    assert load_chunks(active_path)[0].text == "신규 본문"


def test_graph_seed_omits_quarantined_registry_concepts(tmp_path: Path) -> None:
    registry = _registry_with_one_valid_and_one_quarantined(tmp_path)
    assert registry.integrity_report.state == "legacy_unverifiable"
    graph_path = tmp_path / "graph.sqlite"
    store = GraphStore(graph_path, build_mode=True)
    try:
        PolicyReviewExtractor(store, ontology_registry=registry)._seed_ontology_registry_nodes()
        store.commit()
        node_ids = {
            row["node_id"]
            for row in store.query("SELECT node_id FROM graph_nodes ORDER BY node_id")
        }
        aliases = {
            row["alias"]
            for row in store.query("SELECT alias FROM graph_aliases ORDER BY alias")
        }
    finally:
        store.close()

    assert node_ids == {"cond_검증개념"}
    assert "격리 표현" not in aliases
    assert "검증 표현" in aliases


def test_strict_graph_build_does_not_publish_when_registry_is_not_valid(tmp_path: Path) -> None:
    class _InvalidRegistry(_ValidRegistry):
        integrity_report = SimpleNamespace(
            state="stale",
            manifest_content_hash="ontology-hash",
            quarantined_concept_ids=(),
        )

    output_path = tmp_path / "graph.sqlite"
    output_path.write_text("existing-output", encoding="utf-8")

    with pytest.raises(ValueError, match="valid ontology integrity state"):
        graph_build.build_graph(
            chunks_path=tmp_path / "chunks.jsonl",
            standard_db_path=tmp_path / "standard.sqlite",
            output_db_path=output_path,
            manifest_path=tmp_path / "graph_manifest.json",
            low_confidence_report_path=tmp_path / "low_confidence.jsonl",
            strict=True,
            ontology_registry=_InvalidRegistry(),
        )

    assert output_path.read_text(encoding="utf-8") == "existing-output"
    assert not (tmp_path / "graph_manifest.json").exists()
