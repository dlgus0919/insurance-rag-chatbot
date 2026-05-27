import json

import pytest

from src.llm.openai_compatible_client import OpenAICompatibleClient


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


class DummyResponse:
    def __init__(self, status_code, lines):
        self.status_code = status_code
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def iter_lines(self):
        return self.lines


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
