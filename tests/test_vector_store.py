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


def test_query_with_filter_matches_codes_exactly(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["ch_000001", "ch_000002", "ch_000003"],
        embeddings=np.asarray([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32),
        metadatas=[
            {"page_start": 1, "page_end": 1, "codes": ["Q2333"]},
            {"page_start": 2, "page_end": 2, "codes": ["Q23330"]},
            {"page_start": 3, "page_end": 3, "codes": ["AA157"]},
        ],
        documents=["식도조루술", "다른 코드", "진찰료"],
    )

    hits = store.query_with_filter(np.asarray([1.0, 0.0], dtype=np.float32), ["Q2333"], top_k=5)

    assert [hit.id for hit in hits] == ["ch_000001"]


def test_query_with_filter_returns_empty_when_no_code_match(tmp_path) -> None:
    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["ch_000001"],
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        metadatas=[{"page_start": 1, "page_end": 1, "codes": ["AA157"]}],
        documents=["진찰료"],
    )

    assert store.query_with_filter(np.asarray([1.0, 0.0], dtype=np.float32), ["Q2333"], top_k=5) == []
