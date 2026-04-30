import requests

from src.llm.ollama_client import OllamaClient


class DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self.payload = payload or {}

    def json(self):
        return self.payload


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
