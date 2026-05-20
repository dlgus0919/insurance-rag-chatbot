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


def test_generate_reports_connection_error(monkeypatch) -> None:
    client = OpenAICompatibleClient("gpt-oss-20b", base_url="http://localhost:9/v1", api_key="EMPTY")

    with pytest.raises(RuntimeError, match="SGLang 호출 실패"):
        client.generate("hello")


def test_extract_final_content_removes_harmony_markers() -> None:
    from src.llm.openai_compatible_client import _extract_final_content

    content = "<|channel|>analysis<|message|>hidden<|end|><|start|>assistant<|channel|>final<|message|>최종 답변입니다.<|return|>"

    assert _extract_final_content(content) == "최종 답변입니다."
