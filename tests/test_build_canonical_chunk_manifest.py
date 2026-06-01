from __future__ import annotations

import json
from pathlib import Path

from scripts.build_canonical_chunk_manifest import build_manifest
from src.parser.chunker import Chunk, save_chunks


def _write_mapping(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_manifest_uses_v2_as_canonical_and_keeps_unmatched_v1(tmp_path: Path) -> None:
    v2_path = tmp_path / "chunks_v2_manual.jsonl"
    v1_path = tmp_path / "chunks_v1_original_ocr.jsonl"
    combined_path = tmp_path / "chunks_v1_v2_combined.jsonl"
    mapping_dir = tmp_path / "mapping"

    save_chunks(
        [
            Chunk(
                id="실무가이드_v2_manual_ch_000111",
                text="v2 matched",
                metadata={"doc_short": "실무가이드", "page_start": 80, "page_end": 80},
            ),
            Chunk(
                id="실무가이드_v2_manual_ch_000222",
                text="v2 standalone",
                metadata={"doc_short": "실무가이드", "page_start": 81, "page_end": 81},
            ),
        ],
        v2_path,
    )
    save_chunks(
        [
            Chunk(
                id="실무가이드_v1_original_ch_900001",
                text="v1 matched",
                metadata={"doc_short": "실무가이드", "page_start": 80, "page_end": 80},
            ),
            Chunk(
                id="실무가이드_v1_original_ch_900999",
                text="v1 unmatched",
                metadata={"doc_short": "실무가이드", "page_start": 99, "page_end": 99},
            ),
        ],
        v1_path,
    )
    save_chunks(
        [
            Chunk(
                id="실무가이드_v2_manual_ch_000111",
                text="combined matched",
                metadata={
                    "doc_short": "실무가이드",
                    "page_start": 80,
                    "page_end": 80,
                    "canonical_chunk_id": "실무가이드_ch_000111",
                    "source_chunk_id": "실무가이드_ch_000111",
                },
            ),
            Chunk(
                id="실무가이드_v2_manual_ch_000333",
                text="combined only v2 manual",
                metadata={
                    "doc_short": "실무가이드",
                    "page_start": 82,
                    "page_end": 82,
                    "canonical_chunk_id": "실무가이드_ch_000333",
                    "source_chunk_id": "실무가이드_ch_000333",
                    "ocr_version": "v2_manual",
                },
            ),
        ],
        combined_path,
    )
    _write_mapping(
        mapping_dir / "v1_v2_pairs_실무가이드.jsonl",
        [
            {
                "v1_chunk_id": "실무가이드_v1_original_ch_900001",
                "canonical_chunk_id": "실무가이드_ch_000111",
            }
        ],
    )

    manifest = build_manifest(
        v2_chunks_path=v2_path,
        v1_chunks_path=v1_path,
        combined_chunks_path=combined_path,
        mapping_dir=mapping_dir,
    )

    assert len(manifest) == 4

    matched = next(row for row in manifest if row["canonical_chunk_id"] == "실무가이드_ch_000111")
    assert matched["source_variants"]["v2_only"]["variant_chunk_id"] == "실무가이드_v2_manual_ch_000111"
    assert matched["source_variants"]["v1"]["variant_chunk_id"] == "실무가이드_v1_original_ch_900001"
    assert matched["source_variants"]["v1_v2_combined"][0]["variant_chunk_id"] == "실무가이드_v2_manual_ch_000111"

    unmatched_v1 = next(row for row in manifest if row["canonical_chunk_id"] == "실무가이드_ch_900999")
    assert unmatched_v1["source_variants"]["v1"]["variant_chunk_id"] == "실무가이드_v1_original_ch_900999"

    combined_only_v2 = next(row for row in manifest if row["canonical_chunk_id"] == "실무가이드_ch_000333")
    assert combined_only_v2["source_variants"]["v2_only"]["variant_chunk_id"] == "실무가이드_ch_000333"
    assert combined_only_v2["source_variants"]["v1_v2_combined"][0]["variant_chunk_id"] == "실무가이드_v2_manual_ch_000333"
