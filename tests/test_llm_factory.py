import pytest

from src.llm import factory


class FakeOllama:
    provider = "ollama"

    def __init__(self, host: str, model: str):
        self.host = host
        self.model = model

    def list_models(self):
        return ["gemma3:4b", "gemma3:1b"]


class FakeOpenAI:
    provider = "openai"

    def __init__(self, model: str):
        self.model = model


def test_is_openai_model_accepts_prefix_and_gpt_models() -> None:
    assert factory.is_openai_model("gpt-5-mini") is True
    assert factory.is_openai_model("openai:gpt-4.1-nano") is True
    assert factory.is_openai_model("gemma3:4b") is False


def test_model_info_and_label_for_known_and_custom_models() -> None:
    info = factory.get_openai_model_info("gpt-5-mini")
    custom = factory.get_openai_model_info("gpt-6-tiny")

    assert info["family"] == "GPT-5"
    assert info["size"] == "mini"
    assert "Cloud · OpenAI · GPT-5 mini" in factory.format_model_label("gpt-5-mini", "openai")
    assert custom["use_case"] == "사용자 정의"


def test_parse_openai_candidate_models() -> None:
    assert factory.parse_openai_candidate_models("gpt-5-mini, gpt-4.1-nano") == ["gpt-5-mini", "gpt-4.1-nano"]
    assert "gpt-5-mini" in factory.parse_openai_candidate_models("")


def test_list_available_models_respects_env(monkeypatch) -> None:
    monkeypatch.setattr(factory, "OllamaClient", FakeOllama)
    monkeypatch.setenv("ALLOW_OLLAMA", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    grouped = factory.list_available_models()

    assert grouped["local"] == ["gemma3:4b", "gemma3:1b"]
    assert "gpt-5-mini" in grouped["cloud"]


def test_list_available_models_hides_groups(monkeypatch) -> None:
    monkeypatch.setattr(factory, "OllamaClient", FakeOllama)
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert factory.list_available_models() == {"local": [], "cloud": []}


def test_build_llm_routes_to_ollama(monkeypatch) -> None:
    monkeypatch.setattr(factory, "OllamaClient", FakeOllama)
    monkeypatch.setenv("ALLOW_OLLAMA", "true")

    llm = factory.build_llm("gemma3:4b")

    assert isinstance(llm, FakeOllama)
    assert llm.provider == "ollama"


def test_build_llm_rejects_openai_without_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        factory.build_llm("gpt-5-mini")
