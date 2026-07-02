from __future__ import annotations

import json
from pathlib import Path

import scripts.build_index_from_canonical_manifest as builder
from src.parser.chunker import Chunk, load_chunks, save_chunks


def test_build_index_from_manifest_includes_active_source_overlay(
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
                        "metadata": {"content_type": "text"},
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
    chunks_output = tmp_path / "processed" / "chunks.jsonl"
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        builder,
        "build_index",
        lambda *, chunks_path, index_root: calls.append((chunks_path, index_root)),
    )

    result = builder.build_index_from_manifest(
        canonical_manifest=manifest_path,
        index_mode="v2_only",
        chunks_output=chunks_output,
        index_root=tmp_path / "index",
        active_source_chunks=active_chunks_path,
    )

    chunks = load_chunks(chunks_output)
    assert [chunk.id for chunk in chunks] == ["canon-001-v2", "intake:intake-001:0001"]
    assert chunks[1].metadata["source_status"] == "active_intake_source"
    assert result["chunk_count"] == 2
    assert calls == [(chunks_output, tmp_path / "index")]

