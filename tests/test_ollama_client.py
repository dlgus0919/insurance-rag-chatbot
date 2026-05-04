import requests
import json as jsonlib

from src.llm.ollama_client import OllamaClient


class DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None, lines: list[bytes] | None = None):
        self.status_code = status_code
        self.payload = payload or {}
        self.lines = lines or []

    def json(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def iter_lines(self):
        return iter(self.lines)


def test_ollama_generate_posts_non_stream_request(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse(200, {"response": "답변"})

    monkeypatch.setattr(requests, "post", fake_post)
    client = OllamaClient("http://localhost:11434", "qwen2.5:3b-instruct", num_ctx=16384)

    assert client.generate("질문", system="규칙") == "답변"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["json"]["stream"] is False
    assert captured["json"]["model"] == "qwen2.5:3b-instruct"
    assert captured["json"]["options"]["num_ctx"] == 16384


def test_ollama_generate_allows_num_ctx_override(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return DummyResponse(200, {"response": "답변"})

    monkeypatch.setattr(requests, "post", fake_post)
    client = OllamaClient("http://localhost:11434", "model", num_ctx=16384)

    client.generate("질문", num_ctx=4096)

    assert captured["json"]["options"]["num_ctx"] == 4096


def test_ollama_health_false_on_connection_error(monkeypatch) -> None:
    def fake_get(url, timeout):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", fake_get)

    assert OllamaClient("http://localhost:11434", "model").health() is False


def test_ollama_list_models_returns_names(monkeypatch) -> None:
    def fake_get(url, timeout):
        return DummyResponse(200, {"models": [{"name": "gemma3:4b"}, {"name": "gemma3:1b"}]})

    monkeypatch.setattr(requests, "get", fake_get)

    assert OllamaClient("http://localhost:11434", "model").list_models() == ["gemma3:4b", "gemma3:1b"]


def test_ollama_list_models_returns_empty_on_error(monkeypatch) -> None:
    def fake_get(url, timeout):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", fake_get)

    assert OllamaClient("http://localhost:11434", "model").list_models() == []


def test_ollama_generate_stream_yields_tokens(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json, stream, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["stream"] = stream
        return DummyResponse(
            200,
            lines=[
                jsonlib.dumps({"response": "답"}, ensure_ascii=False).encode("utf-8"),
                jsonlib.dumps({"response": "변"}, ensure_ascii=False).encode("utf-8"),
                b'{"done": true}',
            ],
        )

    monkeypatch.setattr(requests, "post", fake_post)
    client = OllamaClient("http://localhost:11434", "model", num_ctx=16384)

    tokens = list(client.generate_stream("질문", system="규칙", temperature=0.1))

    assert tokens == ["답", "변"]
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["json"]["stream"] is True
    assert captured["json"]["options"]["num_ctx"] == 16384
    assert captured["stream"] is True
