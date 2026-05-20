import sys
import types

from src.retrieval.reranker import Reranker


def test_reranker_offline_mode_blocks_remote_download(monkeypatch) -> None:
    calls = []

    class FakeCrossEncoder:
        def __init__(self, model_name: str, **kwargs):
            calls.append((model_name, kwargs))
            if kwargs.get("local_files_only"):
                raise OSError("missing local model")

    module = types.ModuleType("sentence_transformers")
    module.CrossEncoder = FakeCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    reranker = Reranker(model_name="BAAI/bge-reranker-v2-m3", enabled=True, offline_mode=True)

    assert reranker.enabled is False
    assert calls == [("BAAI/bge-reranker-v2-m3", {"max_length": 512, "local_files_only": True})]
