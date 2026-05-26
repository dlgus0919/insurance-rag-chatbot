import pytest

from src.api.routes import system


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_system_status_uses_current_index_paths(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    default_index = data_dir / "index"
    v2_index = data_dir / "index_v2_manual"
    combined_index = data_dir / "index_v1_v2_combined"
    for directory in [
        data_dir / "processed",
        default_index / "chroma",
        v2_index / "chroma",
        combined_index / "chroma",
        default_index / "graph",
        default_index / "relational",
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    chunks_path = data_dir / "processed" / "chunks.jsonl"
    users_path = tmp_path / "users.json"
    for path in [
        chunks_path,
        default_index / "bm25.pkl",
        default_index / "graph" / "insurance_graph.sqlite",
        default_index / "relational" / "standard_codes.sqlite",
        users_path,
    ]:
        path.write_text("ok")

    monkeypatch.setattr(system.config, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(system.config, "CHUNKS_PATH", chunks_path)
    monkeypatch.setattr(system.config, "BM25_PATH", default_index / "bm25.pkl")
    monkeypatch.setattr(system.config, "CHROMA_DIR", default_index / "chroma")
    monkeypatch.setattr(system.config, "GRAPH_INDEX_PATH", default_index / "graph" / "insurance_graph.sqlite")
    monkeypatch.setattr(system.config, "STANDARD_CODES_DB_PATH", default_index / "relational" / "standard_codes.sqlite")
    monkeypatch.setenv("USERS_JSON_PATH", str(users_path))

    response = await system.status()

    assert response.status == "ok"
    assert response.paths["chunks"] is True
    assert response.paths["bm25"] is True
    assert response.paths["chroma"] is True
    assert response.paths["bm25_v2_only"] is False
    assert response.paths["chroma_v2_only"] is True
    assert response.paths["bm25_v1_v2_combined"] is False
    assert response.paths["chroma_v1_v2_combined"] is True
    assert response.paths["graph"] is True
    assert response.paths["relational"] is True
    assert response.paths["users"] is True
