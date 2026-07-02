from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import src.graph.build as graph_build
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
    )

    assert saved_chunk_ids[0] == ["canon-001-v2", "intake:intake-001:0001"]
    manifest = json.loads((tmp_path / "graph_manifest.json").read_text(encoding="utf-8"))
    assert manifest["active_source_chunks_path"] == str(active_chunks_path)


def test_build_graph_merges_active_source_overlay_from_fallback_chunks(tmp_path: Path) -> None:
    base_chunks = [Chunk(id="base-001", text="기존 본문", metadata={})]
    active_chunks = [Chunk(id="intake:intake-001:0001", text="신규 본문", metadata={})]
    active_path = tmp_path / "active" / "chunks.jsonl"
    save_chunks(active_chunks, active_path)

    merged = graph_build._merge_active_source_chunks(base_chunks, active_path)

    assert [chunk.id for chunk in merged] == ["base-001", "intake:intake-001:0001"]
    assert load_chunks(active_path)[0].text == "신규 본문"

