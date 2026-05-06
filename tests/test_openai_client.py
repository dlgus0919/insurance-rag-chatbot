import json

import pytest
import requests

from src.llm.openai_client import OpenAIClient


class DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None, lines: list[bytes] | None = None):
        self.status_code = status_code
        self.payload = payload or {}
        self.lines = lines or []
        self.text = json.dumps(self.payload, ensure_ascii=False)

    def json(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def iter_lines(self):
        return iter(self.lines)


def test_openai_client_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError):
        OpenAIClient("gpt-5-mini")


def test_payload_contains_chat_messages() -> None:
    client = OpenAIClient("gpt-5-mini", api_key="sk-test", max_tokens=123)

    payload = client._payload("질문", "규칙", 0.1, stream=False)

    assert payload["model"] == "gpt-5-mini"
    assert payload["messages"] == [
        {"role": "system", "content": "규칙"},
        {"role": "user", "content": "질문"},
    ]
    assert payload["max_completion_tokens"] == 123
    assert "max_tokens" not in payload
    assert "temperature" not in payload


def test_payload_keeps_legacy_options_for_gpt4o() -> None:
    client = OpenAIClient("gpt-4o", api_key="sk-test", max_tokens=123)

    payload = client._payload("질문", "규칙", 0.1, stream=False)

    assert payload["model"] == "gpt-4o"
    assert payload["max_tokens"] == 123
    assert payload["temperature"] == 0.1
    assert "max_completion_tokens" not in payload


def test_generate_posts_request_and_saves_usage(monkeypatch) -> None:
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return DummyResponse(
            200,
            {
                "choices": [{"message": {"content": " 답변 "}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    monkeypatch.setattr(requests, "post", fake_post)
    client = OpenAIClient("gpt-5-mini", api_key="sk-test")

    assert client.generate("질문", system="규칙", temperature=0.2) == "답변"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["stream"] is False
    assert client.last_usage == {"prompt_tokens": 10, "completion_tokens": 5}


def test_generate_raises_on_http_error(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return DummyResponse(401, {"error": "bad key"})

    monkeypatch.setattr(requests, "post", fake_post)
    client = OpenAIClient("gpt-5-mini", api_key="sk-test")

    with pytest.raises(RuntimeError, match="status=401"):
        client.generate("질문")


def test_generate_stream_yields_tokens(monkeypatch) -> None:
    captured = {}

    def fake_post(url, headers, json, stream, timeout):
        captured["stream"] = stream
        captured["json"] = json
        return DummyResponse(
            200,
            lines=[
                'data: {"choices":[{"delta":{"content":"답"}}]}'.encode("utf-8"),
                'data: {"choices":[{"delta":{"content":"변"}}]}'.encode("utf-8"),
                b"data: [DONE]",
            ],
        )

    monkeypatch.setattr(requests, "post", fake_post)
    client = OpenAIClient("gpt-5-mini", api_key="sk-test")

    assert list(client.generate_stream("질문", system="규칙")) == ["답", "변"]
    assert captured["stream"] is True
    assert captured["json"]["stream"] is True


def test_generate_stream_raises_with_response_body(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return DummyResponse(400, {"error": {"message": "unsupported parameter: temperature"}})

    monkeypatch.setattr(requests, "post", fake_post)
    client = OpenAIClient("gpt-5-mini", api_key="sk-test")

    with pytest.raises(RuntimeError, match="unsupported parameter"):
        list(client.generate_stream("질문"))
