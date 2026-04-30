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
    client = OllamaClient("http://localhost:11434", "qwen2.5:3b-instruct")

    assert client.generate("질문", system="규칙") == "답변"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["json"]["stream"] is False
    assert captured["json"]["model"] == "qwen2.5:3b-instruct"


def test_ollama_health_false_on_connection_error(monkeypatch) -> None:
    def fake_get(url, timeout):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", fake_get)

    assert OllamaClient("http://localhost:11434", "model").health() is False
