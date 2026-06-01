from __future__ import annotations

from src.graph.vector_sync import (
    EvidenceRow,
    check_evidence_sync,
    graph_chunk_fallback_ids,
    summarize_results,
)


class FakeCollection:
    def __init__(self) -> None:
        self.ids = {
            "direct_ch_001",
            "자사_SOL건강_ch_011755",
        }
        self.canonical_chunk_ids = {
            "canonical_001": ("mapped_canonical_001", {"canonical_chunk_id": "canonical_001"}),
        }
        self.source_chunk_ids = {
            "legacy_source_001": ("mapped_ch_001", {"source_chunk_id": "legacy_source_001"}),
        }
        self.doc_pages = {
            "약관": [
                ("약관_ch_000010", {"doc_short": "약관", "page_start": 10, "page_end": 10}),
            ],
            "없는문서": [],
        }

    def get(self, ids=None, where=None, include=None):  # noqa: ANN001, D102
        if ids is not None:
            return {"ids": [item for item in ids if item in self.ids], "metadatas": []}
        if where is not None:
            canonical_chunk_id = where.get("canonical_chunk_id")
            if isinstance(canonical_chunk_id, dict):
                values = canonical_chunk_id.get("$in", [])
                rows = [self.canonical_chunk_ids[value] for value in values if value in self.canonical_chunk_ids]
                return {
                    "ids": [entry_id for entry_id, _ in rows],
                    "metadatas": [metadata for _, metadata in rows],
                }
            source_chunk_id = where.get("source_chunk_id")
            if isinstance(source_chunk_id, dict):
                values = source_chunk_id.get("$in", [])
                rows = [self.source_chunk_ids[value] for value in values if value in self.source_chunk_ids]
                return {
                    "ids": [entry_id for entry_id, _ in rows],
                    "metadatas": [metadata for _, metadata in rows],
                }
            doc_short = where.get("doc_short")
            entries = self.doc_pages.get(doc_short, [])
            return {
                "ids": [entry_id for entry_id, _ in entries],
                "metadatas": [metadata for _, metadata in entries],
            }
        return {"ids": [], "metadatas": []}


def test_graph_chunk_fallback_ids_handles_v2_manual_suffix() -> None:
    fallbacks = graph_chunk_fallback_ids("자사_SOL건강_v2_manual_ch_011755")

    assert "자사_SOL건강_ch_011755" in fallbacks
    assert len(fallbacks) == len(set(fallbacks))


def test_check_evidence_sync_classifies_direct_fallback_doc_page_and_missing() -> None:
    rows = [
        EvidenceRow("ev_direct", "direct_ch_001", None, None, "약관", 1, 1),
        EvidenceRow("ev_canonical", "graph_canonical_001", "canonical_001", None, "약관", 4, 4),
        EvidenceRow("ev_source", "graph_only_001", None, "legacy_source_001", "약관", 5, 5),
        EvidenceRow("ev_fallback", "자사_SOL건강_v2_manual_ch_011755", None, None, "자사_SOL건강", 384, 384),
        EvidenceRow("ev_page", "약관_missing_ch_999999", None, None, "약관", 10, 10),
        EvidenceRow("ev_missing", "missing_ch_001", None, None, "없는문서", 1, 1),
    ]

    results = check_evidence_sync(rows, FakeCollection())

    assert [result.status for result in results] == [
        "direct_hit",
        "canonical_chunk_hit",
        "source_chunk_hit",
        "fallback_hit",
        "doc_page_hit",
        "missing",
    ]
    assert results[1].matched_id == "mapped_canonical_001"
    assert results[2].matched_id == "mapped_ch_001"
    assert results[3].matched_id == "자사_SOL건강_ch_011755"
    assert results[4].matched_id == "약관_ch_000010"


def test_summarize_results_reports_rates_by_doc() -> None:
    rows = [
        EvidenceRow("ev_direct", "direct_ch_001", None, None, "약관", 1, 1),
        EvidenceRow("ev_page", "약관_missing_ch_999999", None, None, "약관", 10, 10),
        EvidenceRow("ev_missing", "missing_ch_001", None, None, "없는문서", 1, 1),
    ]
    results = check_evidence_sync(rows, FakeCollection())

    summary = summarize_results(results)

    assert summary["total"] == 3
    assert summary["hit_rate"] == 0.6667
    assert summary["direct_hit_rate"] == 0.3333
    assert summary["fallback_recovery_rate"] == 0.3333
    assert summary["by_doc_short"]["약관"]["total"] == 2
