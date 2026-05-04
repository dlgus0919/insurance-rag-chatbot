import numpy as np

from src.retrieval.vector_store import VectorStore


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
