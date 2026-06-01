#!/usr/bin/env python3
"""Backfill stable chunk lookup metadata for chunks, Chroma, and GraphDB."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.parser.chunker import Chunk, load_chunks, save_chunks
from src.retrieval.chunk_lookup import build_chunk_lookup_metadata, canonical_source_chunk_id
from src.retrieval.index_mode import INDEX_MODES, resolve_index_paths
from src.retrieval.vector_store import VectorStore, _decode_metadata, _encode_metadata


def _update_chunks_default(path: Path) -> tuple[int, dict[str, dict[str, str]]]:
    chunks = load_chunks(path)
    changed = 0
    lookup: dict[str, dict[str, str]] = {}
    updated: list[Chunk] = []
    for chunk in chunks:
        metadata = build_chunk_lookup_metadata(chunk.id, chunk.metadata)
        if metadata != chunk.metadata:
            changed += 1
        lookup[chunk.id] = {
            "canonical_chunk_id": str(metadata["canonical_chunk_id"]),
            "source_chunk_id": str(metadata["source_chunk_id"]),
        }
        updated.append(Chunk(id=chunk.id, text=chunk.text, metadata=metadata))
    if changed:
        save_chunks(updated, path)
    return changed, lookup


def _update_chunks_combined(path: Path) -> tuple[int, dict[str, dict[str, str]]]:
    chunks = load_chunks(path)
    changed = 0
    lookup: dict[str, dict[str, str]] = {}
    updated: list[Chunk] = []

    for chunk in chunks:
        metadata = dict(chunk.metadata)
        expected_source_chunk_id = canonical_source_chunk_id(chunk.id)
        metadata = build_chunk_lookup_metadata(expected_source_chunk_id, metadata)
        metadata["canonical_chunk_id"] = str(metadata.get("canonical_chunk_id") or expected_source_chunk_id)
        if metadata.get("source_chunk_id") != expected_source_chunk_id:
            metadata["source_chunk_id"] = expected_source_chunk_id
        if metadata != chunk.metadata:
            changed += 1
        lookup[chunk.id] = {
            "canonical_chunk_id": str(metadata["canonical_chunk_id"]),
            "source_chunk_id": str(metadata["source_chunk_id"]),
        }
        updated.append(Chunk(id=chunk.id, text=chunk.text, metadata=metadata))

    if changed:
        save_chunks(updated, path)
    return changed, lookup


def _backfill_vector_store(chroma_dir: Path, lookup: dict[str, dict[str, str]]) -> int:
    store = VectorStore(chroma_dir)
    result = store.collection.get(include=["metadatas"])
    ids = result.get("ids", []) or []
    metadatas = result.get("metadatas", []) or []

    changed_ids: list[str] = []
    changed_metadatas: list[dict] = []
    for index, chunk_id in enumerate(ids):
        if chunk_id not in lookup:
            continue
        metadata = _decode_metadata(metadatas[index] if index < len(metadatas) else {})
        expected = lookup[chunk_id]
        if (
            str(metadata.get("canonical_chunk_id") or "") == expected["canonical_chunk_id"]
            and str(metadata.get("source_chunk_id") or "") == expected["source_chunk_id"]
        ):
            continue
        metadata["canonical_chunk_id"] = expected["canonical_chunk_id"]
        metadata["source_chunk_id"] = expected["source_chunk_id"]
        changed_ids.append(chunk_id)
        changed_metadatas.append(_encode_metadata(metadata))

    if changed_ids:
        batch_size = min(getattr(store, "upsert_batch_size", 1000), 1000)
        for start in range(0, len(changed_ids), batch_size):
            end = min(start + batch_size, len(changed_ids))
            store.collection.update(
                ids=changed_ids[start:end],
                metadatas=changed_metadatas[start:end],
            )
    return len(changed_ids)


def _backfill_graph_db(graph_path: Path, lookup: dict[str, dict[str, str]]) -> int:
    changed = 0
    with sqlite3.connect(graph_path) as conn:
        rows = list(
            conn.execute(
                "SELECT evidence_id, chunk_id, canonical_chunk_id, metadata_json "
                "FROM graph_evidence WHERE chunk_id IS NOT NULL AND chunk_id != ''"
            )
        )
        for evidence_id, chunk_id, canonical_chunk_id, metadata_json in rows:
            expected = lookup.get(str(chunk_id))
            if not expected:
                continue
            metadata = _load_json_object(metadata_json)
            if (
                str(canonical_chunk_id or "") == expected["canonical_chunk_id"]
                and str(metadata.get("canonical_chunk_id") or "") == expected["canonical_chunk_id"]
                and str(metadata.get("source_chunk_id") or "") == expected["source_chunk_id"]
            ):
                continue
            metadata["canonical_chunk_id"] = expected["canonical_chunk_id"]
            metadata["source_chunk_id"] = expected["source_chunk_id"]
            conn.execute(
                "UPDATE graph_evidence SET canonical_chunk_id = ?, metadata_json = ? WHERE evidence_id = ?",
                (expected["canonical_chunk_id"], json.dumps(metadata, ensure_ascii=False), evidence_id),
            )
            changed += 1
        conn.commit()
    return changed


def _load_json_object(raw: object) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        loaded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill stable chunk lookup metadata")
    parser.add_argument("--graph-path", type=Path, default=config.GRAPH_INDEX_PATH)
    args = parser.parse_args()

    default_chunks = ROOT / "data" / "processed" / "chunks.jsonl"
    v2_chunks = ROOT / "data" / "processed" / "chunks_v2_manual.jsonl"
    combined_chunks = ROOT / "data" / "processed" / "chunks_v1_v2_combined.jsonl"
    lookups: dict[str, dict[str, dict[str, str]]] = {}

    changed, lookup = _update_chunks_default(default_chunks)
    lookups["default"] = lookup
    print(f"[backfill] chunks default updated: {changed}")

    changed, lookup = _update_chunks_default(v2_chunks)
    lookups["v2_only"] = lookup
    print(f"[backfill] chunks v2_only updated: {changed}")

    changed, lookup = _update_chunks_combined(combined_chunks)
    lookups["v1_v2_combined"] = lookup
    print(f"[backfill] chunks v1_v2_combined updated: {changed}")

    for mode in INDEX_MODES:
        _, chroma_dir = resolve_index_paths(mode)
        changed = _backfill_vector_store(chroma_dir, lookups[mode])
        print(f"[backfill] chroma {mode} updated: {changed}")

    graph_lookup: dict[str, dict[str, str]] = {}
    for lookup in lookups.values():
        graph_lookup.update(lookup)
    changed = _backfill_graph_db(args.graph_path, graph_lookup)
    print(f"[backfill] graph evidence updated: {changed}")


if __name__ == "__main__":
    main()
