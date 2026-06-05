import json

import pytest

from src.llm.openai_compatible_client import OpenAICompatibleClient, THINKING_EMPTY_FINAL_FALLBACK


def test_payload_uses_openai_chat_completions_shape() -> None:
    client = OpenAICompatibleClient("gpt-oss-20b", base_url="http://localhost:30000/v1", api_key="EMPTY")

    payload = client._payload("질문", "시스템", 0.1, stream=False)

    assert payload["model"] == "gpt-oss-20b"
    assert payload["messages"] == [
        {"role": "system", "content": "시스템"},
        {"role": "user", "content": "질문"},
    ]
    assert payload["temperature"] == 0.1
    assert payload["stream"] is False


def test_payload_disables_nemotron_thinking_for_vllm() -> None:
    client = OpenAICompatibleClient(
        "nemotron-3-nano-30b-a3b-nvfp4",
        base_url="http://localhost:30001/v1",
        api_key="EMPTY",
        provider="vllm",
    )

    payload = client._payload("질문", "시스템", 0.1, stream=True)

    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_payload_disables_qwen_thinking_for_sglang() -> None:
    client = OpenAICompatibleClient(
        "qwen3-next-80b-a3b-thinking-fp8",
        base_url="http://localhost:30000/v1",
        api_key="EMPTY",
        provider="sglang",
    )

    payload = client._payload("질문", "시스템", 0.1, stream=True)

    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in payload


def test_generate_reports_connection_error(monkeypatch) -> None:
    client = OpenAICompatibleClient("gpt-oss-20b", base_url="http://localhost:9/v1", api_key="EMPTY")

    with pytest.raises(RuntimeError, match="SGLang 호출 실패"):
        client.generate("hello")


def test_extract_final_content_removes_harmony_markers() -> None:
    from src.llm.openai_compatible_client import _extract_final_content

    content = "<|channel|>analysis<|message|>hidden<|end|><|start|>assistant<|channel|>final<|message|>최종 답변입니다.<|return|>"

    assert _extract_final_content(content) == "최종 답변입니다."


def test_extract_final_content_preserves_plain_text() -> None:
    from src.llm.openai_compatible_client import _extract_final_content
    assert _extract_final_content("테스트입니다.") == "테스트입니다."


def test_extract_visible_content_removes_thinking_block() -> None:
    from src.llm.openai_compatible_client import _extract_visible_content

    assert _extract_visible_content("reasoning\n</think>\n\n정상입니다.") == "정상입니다."
    assert _extract_visible_content("<think>reasoning</think>최종 답변") == "최종 답변"
    assert _extract_visible_content("reasoning only", require_think_end=True) == ""
    assert (
        _extract_visible_content("Okay, I should think first.", require_think_end=True, fallback_on_hidden=True)
        == THINKING_EMPTY_FINAL_FALLBACK
    )


class DummyResponse:
    def __init__(self, status_code, lines, text="", payload=None, headers=None):
        self.status_code = status_code
        self.lines = lines
        self.text = text
        self._payload = payload or {"choices": [{"message": {"content": "ok"}}]}
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def iter_lines(self):
        return self.lines

    def json(self):
        return self._payload


def test_generate_stream_gemma4_yields_immediately(monkeypatch) -> None:
    client = OpenAICompatibleClient("gemma-4-26b-a4b-nvfp4", base_url="http://localhost:30001/v1", api_key="EMPTY", provider="vllm")

    mock_lines = [
        b'data: {"choices":[{"delta":{"content":"\xed\x85\x8c"}}]}', # '테'
        b'data: {"choices":[{"delta":{"content":"\xec\x8a\xa4\xed\x8a\xb8"}}]}', # '스트'
        b'data: [DONE]'
    ]

    def mock_post(*args, **kwargs):
        return DummyResponse(200, mock_lines)

    monkeypatch.setattr("requests.post", mock_post)

    result = list(client.generate_stream("질문"))
    assert "".join(result) == "테스트"


def test_generate_stream_non_thinking_preserves_whitespace_tokens(monkeypatch) -> None:
    client = OpenAICompatibleClient("gemma-4-26b-a4b-nvfp4", base_url="http://localhost:30001/v1", api_key="EMPTY", provider="vllm")

    mock_lines = [
        b'data: {"choices":[{"delta":{"content":"\xeb\x8b\xb5\xeb\xb3\x80"}}]}',
        b'data: {"choices":[{"delta":{"content":"\\n  "}}]}',
        b'data: {"choices":[{"delta":{"content":"\xec\x9c\xa0\xec\xa7\x80"}}]}',
        b'data: [DONE]',
    ]

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: DummyResponse(200, mock_lines))

    assert "".join(client.generate_stream("질문")) == "답변\n  유지"


def test_generate_stream_harmony_gates_output(monkeypatch) -> None:
    client = OpenAICompatibleClient("gpt-oss-20b", base_url="http://localhost:30000/v1", api_key="EMPTY", provider="sglang")

    mock_lines = [
        b'data: {"choices":[{"delta":{"content":"<|channel|>analysis<|message|>\xec\x83\x9d\xea\xb0\x81"}}]}', # '생각'
        b'data: {"choices":[{"delta":{"content":"<|channel|>final<|message|>\xec\xb5\x9c\xec\xa2\x85"}}]}', # '최종'
        b'data: {"choices":[{"delta":{"content":" \xeb\x8b\xb5\xeb\xb3\x80"}}]}', # ' 답변'
        b'data: [DONE]'
    ]

    def mock_post(*args, **kwargs):
        return DummyResponse(200, mock_lines)

    monkeypatch.setattr("requests.post", mock_post)

    result = list(client.generate_stream("질문"))
    assert "".join(result) == "최종 답변"


def test_generate_retries_after_429(monkeypatch) -> None:
    client = OpenAICompatibleClient("gpt-oss-20b", base_url="http://localhost:30000/v1", api_key="EMPTY")
    responses = iter(
        [
            DummyResponse(429, [], text="too many", headers={"Retry-After": "0"}),
            DummyResponse(200, [], payload={"choices": [{"message": {"content": "정상 답변"}}], "usage": {}}),
        ]
    )

    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: next(responses))

    assert client.generate("질문") == "정상 답변"


def test_generate_qwen_thinking_returns_only_visible_final(monkeypatch) -> None:
    client = OpenAICompatibleClient(
        "qwen3-next-80b-a3b-thinking-fp8",
        base_url="http://localhost:30000/v1",
        api_key="EMPTY",
        provider="sglang",
    )

    def mock_post(*args, **kwargs):
        return DummyResponse(
            200,
            [],
            payload={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Okay, I should think through the instruction.\n"
                                "</think>\n\n정상입니다."
                            )
                        }
                    }
                ],
                "usage": {},
            },
        )

    monkeypatch.setattr("requests.post", mock_post)

    assert client.generate("질문") == "정상입니다."


def test_generate_qwen_thinking_without_end_token_returns_fallback(monkeypatch) -> None:
    client = OpenAICompatibleClient(
        "qwen3-next-80b-a3b-thinking-fp8",
        base_url="http://localhost:30000/v1",
        api_key="EMPTY",
        provider="sglang",
    )

    monkeypatch.setattr(
        "requests.post",
        lambda *args, **kwargs: DummyResponse(
            200,
            [],
            payload={"choices": [{"message": {"content": "Okay, I should think first."}}], "usage": {}},
        ),
    )

    assert client.generate("질문") == THINKING_EMPTY_FINAL_FALLBACK


def test_generate_stream_retries_after_429(monkeypatch) -> None:
    client = OpenAICompatibleClient("gpt-oss-20b", base_url="http://localhost:30000/v1", api_key="EMPTY", provider="sglang")
    responses = iter(
        [
            DummyResponse(429, [], text="too many", headers={"Retry-After": "0"}),
            DummyResponse(
                200,
                [
                    b'data: {"choices":[{"delta":{"content":"<|channel|>final<|message|>\xec\xb5\x9c\xec\xa2\x85"}}]}',
                    b'data: {"choices":[{"delta":{"content":" \xeb\x8b\xb5\xeb\xb3\x80"}}]}',
                    b'data: [DONE]',
                ],
            ),
        ]
    )

    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: next(responses))

    assert "".join(client.generate_stream("질문")) == "최종 답변"


def test_generate_stream_qwen_thinking_gates_until_final(monkeypatch) -> None:
    client = OpenAICompatibleClient(
        "qwen3-next-80b-a3b-thinking-fp8",
        base_url="http://localhost:30000/v1",
        api_key="EMPTY",
        provider="sglang",
    )

    responses = iter(
        [
            DummyResponse(
                200,
                [
                    b'data: {"choices":[{"delta":{"content":"Okay, I should reason first."}}]}',
                    b'data: {"choices":[{"delta":{"content":"</think>\\n\\n\xec\xa0\x95\xec\x83\x81"}}]}',
                    b'data: {"choices":[{"delta":{"content":"\xec\x9e\x85\xeb\x8b\x88\xeb\x8b\xa4."}}]}',
                    b'data: [DONE]',
                ],
            ),
        ]
    )

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: next(responses))

    assert "".join(client.generate_stream("질문")) == "정상입니다."


def test_generate_stream_qwen_thinking_with_disabled_template_final_text(monkeypatch) -> None:
    client = OpenAICompatibleClient(
        "qwen3-next-80b-a3b-thinking-fp8",
        base_url="http://localhost:30000/v1",
        api_key="EMPTY",
        provider="sglang",
    )

    responses = iter(
        [
            DummyResponse(
                200,
                [
                    b'data: {"choices":[{"delta":{"content":"N39.3\xec\x9d\x80 "}}]}',
                    b'data: {"choices":[{"delta":{"content":"\xec\x95\xbd\xea\xb4\x80\xec\x83\x81 \xeb\xb3\xb4\xec\x83\x81 \xec\xa0\x9c\xec\x99\xb8\xec\x9e\x85\xeb\x8b\x88\xeb\x8b\xa4."}}]}',
                    b'data: [DONE]',
                ],
            ),
        ]
    )

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: next(responses))

    assert "".join(client.generate_stream("질문")) == "N39.3은 약관상 보상 제외입니다."


def test_generate_stream_qwen_thinking_without_end_token_returns_fallback(monkeypatch) -> None:
    client = OpenAICompatibleClient(
        "qwen3-next-80b-a3b-thinking-fp8",
        base_url="http://localhost:30000/v1",
        api_key="EMPTY",
        provider="sglang",
    )

    responses = iter(
        [
            DummyResponse(
                200,
                [
                    b'data: {"choices":[{"delta":{"content":"Okay, let\\u0027s tackle this question."}}]}',
                    b'data: {"choices":[{"delta":{"content":" I need to inspect the policy context first."}}]}',
                    b'data: [DONE]',
                ],
            ),
        ]
    )

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: next(responses))

    result = "".join(client.generate_stream("질문"))
    assert result == THINKING_EMPTY_FINAL_FALLBACK
    assert "Okay" not in result
    assert "tackle" not in result
