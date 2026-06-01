from __future__ import annotations

from src.retrieval.canonical_manifest import iter_chunks_for_index_mode


def test_iter_chunks_for_index_mode_preserves_canonical_identity() -> None:
    rows = [
        {
            "canonical_chunk_id": "실무가이드_ch_000111",
            "doc_short": "실무가이드",
            "doc_name": "Claim 실무종합가이드",
            "pdf_filename": "Claim 실무종합가이드.pdf",
            "page_start": 80,
            "page_end": 80,
            "metadata": {"doc_short": "실무가이드", "page_start": 80, "page_end": 80},
            "text": "base text",
            "source_variants": {
                "v2_only": {
                    "variant_chunk_id": "실무가이드_v2_manual_ch_000111",
                    "ocr_version": "v2_manual",
                    "available": True,
                    "text": "v2 text",
                    "metadata": {"source_chunk_id": "실무가이드_ch_000111"},
                },
                "v1_v2_combined": [
                    {
                        "variant_chunk_id": "실무가이드_v2_manual_ch_000111",
                        "ocr_version": "v2_manual",
                        "available": True,
                        "text": "v2 text",
                        "metadata": {"source_chunk_id": "실무가이드_ch_000111"},
                    },
                    {
                        "variant_chunk_id": "실무가이드_v1_original_ch_000111",
                        "ocr_version": "v1_original",
                        "available": True,
                        "text": "v1 text",
                        "metadata": {"source_chunk_id": "실무가이드_ch_000111"},
                    },
                ],
            },
        }
    ]

    v2_chunks = iter_chunks_for_index_mode(rows, "v2_only")
    assert len(v2_chunks) == 1
    assert v2_chunks[0].id == "실무가이드_v2_manual_ch_000111"
    assert v2_chunks[0].metadata["canonical_chunk_id"] == "실무가이드_ch_000111"
    assert v2_chunks[0].metadata["source_chunk_id"] == "실무가이드_ch_000111"

    combined_chunks = iter_chunks_for_index_mode(rows, "v1_v2_combined")
    assert [chunk.id for chunk in combined_chunks] == [
        "실무가이드_v2_manual_ch_000111",
        "실무가이드_v1_original_ch_000111",
    ]
    assert {chunk.metadata["canonical_chunk_id"] for chunk in combined_chunks} == {"실무가이드_ch_000111"}
