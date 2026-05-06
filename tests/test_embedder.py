import sys
import types

import pytest

from src.retrieval.embedder import Embedder


def _install_sentence_transformer(monkeypatch, cls) -> None:
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = cls
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


def test_embedder_defaults_to_local_files_only(monkeypatch) -> None:
    calls = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            calls.append((model_name, kwargs))

    _install_sentence_transformer(monkeypatch, FakeSentenceTransformer)

    Embedder("BAAI/bge-m3")

    assert calls == [("BAAI/bge-m3", {"local_files_only": True})]


def test_embedder_allows_remote_download_when_requested(monkeypatch) -> None:
    calls = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            calls.append((model_name, kwargs))

    _install_sentence_transformer(monkeypatch, FakeSentenceTransformer)

    Embedder("BAAI/bge-m3", allow_remote_download=True)

    assert calls == [("BAAI/bge-m3", {"local_files_only": False})]


def test_embedder_remote_download_failure_message(monkeypatch) -> None:
    class FailingSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            raise OSError("download failed")

    _install_sentence_transformer(monkeypatch, FailingSentenceTransformer)

    with pytest.raises(RuntimeError) as exc_info:
        Embedder("BAAI/bge-m3", allow_remote_download=True)

    message = str(exc_info.value)
    assert "HuggingFace" in message
    assert "다운로드하거나 로드할 수 없습니다" in message
    assert "BAAI/bge-m3" in message
