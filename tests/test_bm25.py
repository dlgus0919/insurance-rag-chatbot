from pathlib import Path

from src.retrieval.bm25 import BM25Index, tokenize


def test_tokenize_keeps_medical_codes() -> None:
    tokens = tokenize("AA157 재진 진찰료와 10100 코드")

    assert "aa157" in tokens
    assert "10100" in tokens


def test_bm25_returns_relevant_document_first(tmp_path: Path) -> None:
    index = BM25Index()
    index.build(
        ["ch_000001", "ch_000002", "ch_000003"],
        ["AA157 재진 진찰료 산정 기준", "B5070 영상검사 세부 기준", "입원료 일반 산정 지침"],
        [
            {"doc_short": "심평원", "page_start": 10, "page_end": 10},
            {"doc_short": "심평원", "page_start": 20, "page_end": 20},
            {"doc_short": "약관", "page_start": 30},
        ],
    )

    hits = index.query("AA157 재진 진찰료", top_k=2)

    assert hits[0].id == "ch_000001"
    assert hits[0].metadata["doc_short"] == "심평원"
    assert hits[0].metadata["page_start"] == 10

    path = tmp_path / "bm25.pkl"
    index.save(path)
    loaded = BM25Index.load(path)

    loaded_hit = loaded.query("영상검사", top_k=1)[0]
    assert loaded_hit.id == "ch_000002"
    assert loaded_hit.metadata["doc_short"] == "심평원"
