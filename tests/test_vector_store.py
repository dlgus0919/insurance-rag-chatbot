import numpy as np

from src.retrieval.chunk_lookup import ChunkLookupRef
from src.retrieval.vector_store import VectorStore


class _FakeCollection:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upsert(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)


def test_vector_store_upsert_and_query_roundtrip(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["ch_000001", "ch_000002"],
        embeddings=np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        metadatas=[
            {"page_start": 1, "page_end": 1, "codes": ["AA157"]},
            {"page_start": 2, "page_end": 2, "codes": []},
        ],
        documents=["재진 진찰료", "영상검사"],
    )

    hits = store.query(np.asarray([1.0, 0.0], dtype=np.float32), top_k=1)

    assert hits[0].id == "ch_000001"
    assert hits[0].metadata["codes"] == ["AA157"]
    assert hits[0].document == "재진 진찰료"


def test_vector_store_upsert_splits_batches() -> None:
    store = VectorStore.__new__(VectorStore)
    store.collection = _FakeCollection()
    store._all_entries_cache = {"stale": True}
    store.upsert_batch_size = 2

    store.upsert(
        ids=["a", "b", "c", "d", "e"],
        embeddings=np.asarray(
            [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2], [0.7, 0.3], [0.6, 0.4]],
            dtype=np.float32,
        ),
        metadatas=[
            {"codes": ["A"]},
            {"codes": ["B"]},
            {"codes": ["C"]},
            {"codes": ["D"]},
            {"codes": ["E"]},
        ],
        documents=["doc-a", "doc-b", "doc-c", "doc-d", "doc-e"],
    )

    assert [call["ids"] for call in store.collection.calls] == [["a", "b"], ["c", "d"], ["e"]]
    assert [len(call["embeddings"]) for call in store.collection.calls] == [2, 2, 1]
    assert store.collection.calls[0]["metadatas"][0]["codes"] == "A"
    assert store.collection.calls[0]["metadatas"][0]["source_chunk_id"] == "a"
    assert store._all_entries_cache is None


def test_query_applies_doc_filter(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["hira", "policy"],
        embeddings=np.asarray([[1.0, 0.0], [0.9, 0.1]], dtype=np.float32),
        metadatas=[
            {"doc_short": "심평원", "page_start": 1, "page_end": 1, "codes": ["AA157"]},
            {"doc_short": "약관", "page_start": 2, "page_end": 2, "codes": ["N39.3"]},
        ],
        documents=["진찰료", "요실금 보상하지 않는 사항"],
    )

    hits = store.query(np.asarray([1.0, 0.0], dtype=np.float32), top_k=2, doc_filter=["약관"])

    assert [hit.id for hit in hits] == ["policy"]
    assert hits[0].metadata["doc_short"] == "약관"


def test_query_with_filter_matches_codes_exactly(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["ch_000001", "ch_000002", "ch_000003"],
        embeddings=np.asarray([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32),
        metadatas=[
            {"page_start": 1, "page_end": 1, "codes": ["Q2333"], "is_code_table": True},
            {"page_start": 2, "page_end": 2, "codes": ["Q23330"]},
            {"page_start": 3, "page_end": 3, "codes": ["AA157"]},
        ],
        documents=["식도조루술", "다른 코드", "진찰료"],
    )

    hits = store.query_with_filter(np.asarray([1.0, 0.0], dtype=np.float32), ["Q2333"], top_k=5)

    assert [hit.id for hit in hits] == ["ch_000001"]


def test_query_with_filter_applies_doc_filter(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["hira", "policy"],
        embeddings=np.asarray([[1.0, 0.0], [0.8, 0.2]], dtype=np.float32),
        metadatas=[
            {"doc_short": "심평원", "page_start": 1, "page_end": 1, "codes": ["AA157"]},
            {"doc_short": "약관", "page_start": 2, "page_end": 2, "codes": ["AA157"]},
        ],
        documents=["AA157 상급종합병원", "AA157 관련 약관 설명"],
    )

    hits = store.query_with_filter(
        np.asarray([1.0, 0.0], dtype=np.float32),
        ["AA157"],
        top_k=5,
        doc_filter=["약관"],
    )

    assert [hit.id for hit in hits] == ["policy"]
    assert hits[0].metadata["doc_short"] == "약관"


def test_query_with_filter_boosts_code_row_over_range_mention(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["range", "row"],
        embeddings=np.asarray([[1.0, 0.0], [0.95, 0.05]], dtype=np.float32),
        metadatas=[
            {"page_start": 80, "page_end": 80, "codes": ["AA157"], "is_code_table": True},
            {"page_start": 101, "page_end": 101, "codes": ["AA157"], "is_code_table": True},
        ],
        documents=["AA153~AA157은 기본진찰료 범위입니다.", "AA157 (5) 상급종합병원 255.79"],
    )

    hits = store.query_with_filter(np.asarray([1.0, 0.0], dtype=np.float32), ["AA157"], top_k=2)

    assert [hit.id for hit in hits] == ["row", "range"]


def test_query_with_filter_returns_empty_when_no_code_match(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["ch_000001"],
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        metadatas=[{"page_start": 1, "page_end": 1, "codes": ["AA157"]}],
        documents=["진찰료"],
    )

    assert store.query_with_filter(np.asarray([1.0, 0.0], dtype=np.float32), ["Q2333"], top_k=5) == []


def test_query_with_filter_prefers_non_table_chunks(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["table", "detail"],
        embeddings=np.asarray([[1.0, 0.0], [0.8, 0.2]], dtype=np.float32),
        metadatas=[
            {"page_start": 1, "page_end": 1, "codes": ["Q2333"], "is_code_table": True},
            {"page_start": 2, "page_end": 2, "codes": ["Q2333"], "is_code_table": False},
        ],
        documents=["Q2333 코드표", "식도조루술 상세 설명"],
    )

    hits = store.query_with_filter(np.asarray([1.0, 0.0], dtype=np.float32), ["Q2333"], top_k=5)

    assert [hit.id for hit in hits] == ["detail"]
    assert hits[0].metadata["is_code_table"] is False


def test_query_with_filter_falls_back_to_table_chunks(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["table"],
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        metadatas=[{"page_start": 1, "page_end": 1, "codes": ["Q2333"], "is_code_table": True}],
        documents=["Q2333 코드표"],
    )

    hits = store.query_with_filter(np.asarray([1.0, 0.0], dtype=np.float32), ["Q2333"], top_k=5)

    assert [hit.id for hit in hits] == ["table"]


def test_get_by_ids_falls_back_from_graph_v2_manual_chunk_id(tmp_path) -> None:
    """GraphDB evidence id의 v2_manual 삽입 표기가 현재 VectorStore id와 달라도 조회한다."""
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["자사_SOL건강_ch_011755"],
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        metadatas=[{"doc_short": "자사_SOL건강", "page_start": 384}],
        documents=["SOL 건강보험 별표7 수술분류표 근거"],
    )

    hits = store.get_by_ids(["자사_SOL건강_v2_manual_ch_011755"])

    assert len(hits) == 1
    assert hits[0].id == "자사_SOL건강_v2_manual_ch_011755"
    assert hits[0].metadata["page_start"] == 384


def test_upsert_normalizes_source_chunk_id_for_combined_ids() -> None:
    store = VectorStore.__new__(VectorStore)
    store.collection = _FakeCollection()
    store._all_entries_cache = {"stale": True}
    store.upsert_batch_size = 10

    store.upsert(
        ids=["심평원_v2_manual_ch_007841"],
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        metadatas=[{"doc_short": "심평원", "page_start": 638}],
        documents=["췌이식술"],
    )

    assert store.collection.calls[0]["metadatas"][0]["source_chunk_id"] == "심평원_ch_007841"


def test_get_by_refs_matches_source_chunk_id_when_collection_id_differs(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["combined_v2_001"],
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        metadatas=[{"doc_short": "실무가이드", "page_start": 80, "source_chunk_id": "실무가이드_ch_000111"}],
        documents=["신1-5종 수술분류표 근거"],
    )

    hits = store.get_by_refs([
        ChunkLookupRef(
            requested_id="실무가이드_v2_manual_ch_009999",
            source_chunk_id="실무가이드_ch_000111",
            doc_short="실무가이드",
            page_start=80,
            page_end=80,
        )
    ])

    assert len(hits) == 1
    assert hits[0].id == "실무가이드_v2_manual_ch_009999"
    assert hits[0].metadata["source_chunk_id"] == "실무가이드_ch_000111"


def test_get_by_doc_page_finds_overlapping_page_range(tmp_path) -> None:
    """GraphDB chunk id 동기화가 깨져도 doc_short/page evidence로 청크를 복구한다."""
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["sol_384", "sol_390"],
        embeddings=np.asarray([[1.0, 0.0], [0.9, 0.1]], dtype=np.float32),
        metadatas=[
            {"doc_short": "자사_SOL건강", "page_start": 384, "page_end": 389},
            {"doc_short": "자사_SOL건강", "page_start": 390, "page_end": 390},
        ],
        documents=["별표7 수술분류표", "다른 페이지"],
    )

    hits = store.get_by_doc_page("자사_SOL건강", 384, 384)

    assert [hit.id for hit in hits] == ["sol_384"]


def test_vector_store_reset_drops_previous_collection_entries(tmp_path) -> None:
    path = tmp_path / "chroma"
    store = VectorStore(path)
    store.upsert(
        ids=["old"],
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        metadatas=[{"page_start": 1, "page_end": 1, "codes": ["AA157"]}],
        documents=["기존 청크"],
    )

    reset_store = VectorStore(path, reset=True)

    assert reset_store.collection.count() == 0
