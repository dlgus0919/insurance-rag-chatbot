from pathlib import Path

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


class FakeSGLang:
    provider = "sglang"

    def __init__(self, model: str, **kwargs):
        self.model = model


def test_is_openai_model_accepts_prefix_and_gpt_models() -> None:
    assert factory.is_openai_model("gpt-5-mini") is True
    assert factory.is_openai_model("openai:gpt-4.1-nano") is True
    assert factory.is_openai_model("sglang:gpt-oss-20b") is False
    assert factory.is_openai_model("gemma3:4b") is False


def test_model_info_and_label_for_known_and_custom_models() -> None:
    info = factory.get_openai_model_info("gpt-5-mini")
    custom = factory.get_openai_model_info("gpt-6-tiny")

    assert info["family"] == "GPT-5"
    assert info["size"] == "mini"
    assert "Cloud · OpenAI · GPT-5 mini" in factory.format_model_label("gpt-5-mini", "openai")
    assert "Local · SGLang · GPT-OSS · 20B · Fallback" == factory.format_model_label("gpt-oss-20b", "sglang")
    assert "온톨로지 주력" in factory.format_model_label("qwen3-30b-a3b-instruct-2507-fp8", "sglang")
    assert "답변 주력" in factory.format_model_label("qwen3-next-80b-a3b-instruct-fp8", "sglang")
    assert "삭제 후보" in factory.format_model_label("gemma-4-26b-a4b-nvfp4", "vllm")
    assert "이미지 후보" in factory.format_model_label("gemma-4-31b-it-nvfp4", "vllm")
    assert "Local · TensorRT-LLM · GPT-OSS · 120B MXFP4 · 실험" == factory.format_model_label(
        "openai/gpt-oss-120b",
        "trtllm",
    )
    assert "Local · TensorRT-LLM · GPT-OSS · 120B MXFP4 · 실험" == factory.format_model_label(
        "/models/gpt-oss-120b",
        "trtllm",
    )
    ontology_info = factory.get_local_model_info("qwen3-30b-a3b-instruct-2507-fp8", "sglang")
    answer_info = factory.get_local_model_info("qwen3-next-80b-a3b-instruct-fp8", "sglang")
    trtllm_info = factory.get_local_model_info("openai/gpt-oss-120b", "trtllm")
    assert ontology_info["status"] == "ontology_primary"
    assert ontology_info["optional"] == "false"
    assert answer_info["status"] == "answer_primary"
    assert answer_info["optional"] == "false"
    assert trtllm_info["status"] == "experimental"
    assert trtllm_info["optional"] == "false"
    local_info = factory.get_local_model_info("gemma-4-26b-a4b-nvfp4", "vllm")
    assert local_info["status"] == "delete_candidate"
    assert local_info["delete_candidate"] == "true"
    assert custom["use_case"] == "사용자 정의"


def test_parse_openai_candidate_models() -> None:
    assert factory.parse_openai_candidate_models("gpt-5-mini, gpt-4.1-nano") == ["gpt-5-mini", "gpt-4.1-nano"]
    assert "gpt-5-mini" in factory.parse_openai_candidate_models("")


def test_list_available_models_respects_env(monkeypatch) -> None:
    monkeypatch.setattr(factory, "OllamaClient", FakeOllama)
    monkeypatch.setenv("ALLOW_OLLAMA", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", False)
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["gpt-oss-20b"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_DIR", Path("/missing"))
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_STRICT_AVAILABLE_MODELS", False)
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "VLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "OLLAMA_MODEL", "gemma3:4b")
    monkeypatch.setattr(factory.config, "OLLAMA_CANDIDATE_MODELS", ["gemma3:4b", "gemma3:1b"])
    monkeypatch.setattr(factory, "_served_models_for_endpoint", lambda endpoint, api_key=None: [])

    grouped = factory.list_available_models()

    assert grouped["sglang"] == ["gpt-oss-20b"]
    assert grouped["ollama"] == ["gemma3:4b", "gemma3:1b"]
    assert "gpt-5-mini" in grouped["openai"]


def test_list_available_models_hides_cloud_in_offline_mode(monkeypatch) -> None:
    monkeypatch.setattr(factory, "OllamaClient", FakeOllama)
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["gpt-oss-20b"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_DIR", Path("/missing"))
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_STRICT_AVAILABLE_MODELS", False)
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "VLLM_DEFAULT_MODEL", "gemma-4-31b-it-nvfp4")
    monkeypatch.setattr(factory.config, "VLLM_CANDIDATE_MODELS", ["gemma-4-31b-it-nvfp4"])
    monkeypatch.setattr(factory.config, "VLLM_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "VLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory, "_served_models_for_endpoint", lambda endpoint, api_key=None: [])

    grouped = factory.list_available_models()

    assert grouped["sglang"] == ["gpt-oss-20b"]
    assert grouped["vllm"] == ["gemma-4-31b-it-nvfp4"]
    assert grouped["ollama"] == []
    assert grouped["openai"] == []


def test_list_runtime_available_models_only_exposes_live_local_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(factory, "OllamaClient", FakeOllama)
    monkeypatch.setenv("ALLOW_OLLAMA", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_DIR", Path("/missing"))
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["gpt-oss-20b"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "VLLM_DEFAULT_MODEL", "gemma-4-26b-a4b-nvfp4")
    monkeypatch.setattr(factory.config, "VLLM_CANDIDATE_MODELS", ["gemma-4-26b-a4b-nvfp4"])
    monkeypatch.setattr(factory.config, "VLLM_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "VLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "VLLM_STRICT_AVAILABLE_MODELS", False)
    monkeypatch.setattr(factory.config, "OLLAMA_MODEL", "gemma3:4b")
    monkeypatch.setattr(factory.config, "OLLAMA_CANDIDATE_MODELS", ["gemma3:4b", "gemma3:1b"])

    def fake_served(endpoint, api_key=None):
        if endpoint.endswith("30000/v1"):
            return ["gpt-oss-20b"]
        return []

    monkeypatch.setattr(factory, "_served_models_for_endpoint", fake_served)

    grouped = factory.list_runtime_available_models()

    assert grouped == {
        "sglang": ["gpt-oss-20b"],
        "vllm": [],
        "trtllm": [],
        "ollama": ["gemma3:4b", "gemma3:1b"],
        "openai": [],
    }


def test_build_llm_routes_to_ollama(monkeypatch) -> None:
    monkeypatch.setattr(factory, "OllamaClient", FakeOllama)
    monkeypatch.setenv("ALLOW_OLLAMA", "true")

    llm = factory.build_llm("gemma3:4b", provider="ollama")

    assert isinstance(llm, FakeOllama)
    assert llm.provider == "ollama"


def test_build_llm_routes_to_sglang(monkeypatch) -> None:
    class FakeClient:
        provider = "sglang"

        def __init__(self, model: str):
            self.model = model

    import src.llm.openai_compatible_client as module

    monkeypatch.setattr(module, "OpenAICompatibleClient", FakeClient)

    llm = factory.build_llm("gpt-oss-20b", provider="sglang")

    assert isinstance(llm, FakeClient)
    assert llm.provider == "sglang"
    assert llm.model == "gpt-oss-20b"




def test_build_llm_routes_to_vllm(monkeypatch) -> None:
    class FakeClient:
        provider = "vllm"

        def __init__(self, model: str, **kwargs):
            self.model = model
            self.kwargs = kwargs
            self.provider = kwargs.get("provider")

    import src.llm.openai_compatible_client as module

    monkeypatch.setattr(module, "OpenAICompatibleClient", FakeClient)
    monkeypatch.setattr(factory.config, "VLLM_API_KEY", "EMPTY")
    monkeypatch.setattr(factory.config, "VLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "vllm_base_url_for_model", lambda model: "http://127.0.0.1:30001/v1")

    llm = factory.build_llm("gemma-4-26b-a4b-nvfp4", provider="vllm")

    assert isinstance(llm, FakeClient)
    assert llm.provider == "vllm"
    assert llm.model == "gemma-4-26b-a4b-nvfp4"
    assert llm.kwargs["base_url"] == "http://127.0.0.1:30001/v1"


def test_build_llm_rejects_openai_without_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        factory.build_llm("gpt-5-mini", provider="openai")


def test_list_available_models_does_not_discover_local_sglang_directories(monkeypatch, tmp_path) -> None:
    staged = tmp_path / "qwen3-next-80b-a3b-instruct-fp8"
    staged.mkdir()
    (staged / "config.json").write_text("{}", encoding="utf-8")
    (staged / "tokenizer.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(factory.config, "SGLANG_MODEL_DIR", tmp_path)
    monkeypatch.setattr(factory.config, "SGLANG_STRICT_AVAILABLE_MODELS", False)
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["gpt-oss-20b"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setattr(factory, "_served_models_for_endpoint", lambda endpoint, api_key=None: [])
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)

    grouped = factory.list_available_models()

    assert grouped["sglang"] == ["gpt-oss-20b"]


def test_disabled_sglang_models_are_hidden_and_rejected(monkeypatch, tmp_path) -> None:
    staged = tmp_path / "gemma-4-26b-a4b-nvfp4"
    staged.mkdir()
    (staged / "config.json").write_text("{}", encoding="utf-8")
    (staged / "tokenizer.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(factory.config, "SGLANG_MODEL_DIR", tmp_path)
    monkeypatch.setattr(factory.config, "SGLANG_STRICT_AVAILABLE_MODELS", False)
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["gpt-oss-20b", "gemma-4-26b-a4b-nvfp4"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", {"gemma-4-26b-a4b-nvfp4"})
    monkeypatch.setattr(factory, "_served_models_for_endpoint", lambda endpoint, api_key=None: [])
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)

    grouped = factory.list_available_models()

    assert grouped["sglang"] == ["gpt-oss-20b"]
    with pytest.raises(RuntimeError, match="비활성화"):
        factory.build_llm("gemma-4-26b-a4b-nvfp4", provider="sglang")


def test_gpt_oss_120b_is_not_exposed_by_default_and_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "qwen3-next-80b-a3b-instruct-fp8")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["qwen3-next-80b-a3b-instruct-fp8", "gpt-oss-120b"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_STRICT_AVAILABLE_MODELS", False)
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", {"gpt-oss-120b"})
    monkeypatch.setattr(factory, "_served_models_for_endpoint", lambda endpoint, api_key=None: [])
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)

    grouped = factory.list_available_models()

    assert grouped["sglang"] == ["qwen3-next-80b-a3b-instruct-fp8"]
    with pytest.raises(RuntimeError, match="비활성화"):
        factory.build_llm("gpt-oss-120b", provider="sglang")


def test_trtllm_gpt_oss_120b_is_exposed_only_when_endpoint_advertises_it(monkeypatch) -> None:
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "qwen3-next-80b-a3b-instruct-fp8")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["qwen3-next-80b-a3b-instruct-fp8"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_STRICT_AVAILABLE_MODELS", True)
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "VLLM_DEFAULT_MODEL", "gemma-4-31b-it-nvfp4")
    monkeypatch.setattr(factory.config, "VLLM_CANDIDATE_MODELS", ["gemma-4-31b-it-nvfp4"])
    monkeypatch.setattr(factory.config, "VLLM_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "VLLM_STRICT_AVAILABLE_MODELS", True)
    monkeypatch.setattr(factory.config, "VLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "TRTLLM_BASE_URL", "http://127.0.0.1:8355/v1")
    monkeypatch.setattr(factory.config, "TRTLLM_API_KEY", "EMPTY")
    monkeypatch.setattr(factory.config, "TRTLLM_DEFAULT_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(factory.config, "TRTLLM_CANDIDATE_MODELS", ["openai/gpt-oss-120b"])
    monkeypatch.setattr(factory.config, "TRTLLM_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "TRTLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "TRTLLM_STRICT_AVAILABLE_MODELS", True)
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)

    def fake_served(endpoint, api_key=None):
        if endpoint.endswith("8355/v1"):
            return ["openai/gpt-oss-120b"]
        return []

    monkeypatch.setattr(factory, "_served_models_for_endpoint", fake_served)

    grouped = factory.list_available_models()
    runtime = factory.list_runtime_available_models()

    assert grouped["sglang"] == []
    assert grouped["vllm"] == []
    assert grouped["trtllm"] == ["openai/gpt-oss-120b"]
    assert runtime["trtllm"] == ["openai/gpt-oss-120b"]


def test_trtllm_local_path_model_id_is_supported_when_endpoint_advertises_it(monkeypatch) -> None:
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "qwen3-next-80b-a3b-instruct-fp8")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["qwen3-next-80b-a3b-instruct-fp8"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_STRICT_AVAILABLE_MODELS", True)
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "VLLM_DEFAULT_MODEL", "gemma-4-31b-it-nvfp4")
    monkeypatch.setattr(factory.config, "VLLM_CANDIDATE_MODELS", ["gemma-4-31b-it-nvfp4"])
    monkeypatch.setattr(factory.config, "VLLM_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "VLLM_STRICT_AVAILABLE_MODELS", True)
    monkeypatch.setattr(factory.config, "VLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "TRTLLM_BASE_URL", "http://127.0.0.1:8355/v1")
    monkeypatch.setattr(factory.config, "TRTLLM_API_KEY", "EMPTY")
    monkeypatch.setattr(factory.config, "TRTLLM_DEFAULT_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(factory.config, "TRTLLM_CANDIDATE_MODELS", ["openai/gpt-oss-120b"])
    monkeypatch.setattr(factory.config, "TRTLLM_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "TRTLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "TRTLLM_STRICT_AVAILABLE_MODELS", True)
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)
    monkeypatch.setattr(factory, "_served_models_for_endpoint", lambda endpoint, api_key=None: ["/models/gpt-oss-120b"] if endpoint.endswith("8355/v1") else [])

    grouped = factory.list_available_models()

    assert grouped["trtllm"] == ["/models/gpt-oss-120b"]


def test_build_llm_routes_to_trtllm(monkeypatch) -> None:
    class FakeClient:
        provider = "trtllm"

        def __init__(self, model: str, **kwargs):
            self.model = model
            self.kwargs = kwargs
            self.provider = kwargs.get("provider")

    import src.llm.openai_compatible_client as module

    monkeypatch.setattr(module, "OpenAICompatibleClient", FakeClient)
    monkeypatch.setattr(factory.config, "TRTLLM_API_KEY", "EMPTY")
    monkeypatch.setattr(factory.config, "TRTLLM_MAX_TOKENS", 4096)
    monkeypatch.setattr(factory.config, "TRTLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "trtllm_base_url_for_model", lambda model: "http://127.0.0.1:8355/v1")

    llm = factory.build_llm("openai/gpt-oss-120b", provider="trtllm")

    assert isinstance(llm, FakeClient)
    assert llm.provider == "trtllm"
    assert llm.model == "openai/gpt-oss-120b"
    assert llm.kwargs["base_url"] == "http://127.0.0.1:8355/v1"
    assert llm.kwargs["api_key"] == "EMPTY"
    assert llm.kwargs["max_tokens"] == 4096


def test_strict_sglang_models_only_exposes_served_models(monkeypatch) -> None:
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_DIR", Path("/missing"))
    monkeypatch.setattr(factory.config, "SGLANG_STRICT_AVAILABLE_MODELS", True)
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["gpt-oss-20b", "gemma-4-26b-a4b-nvfp4"])
    monkeypatch.setattr(
        factory.config,
        "SGLANG_MODEL_ENDPOINTS",
        {"gpt-oss-20b": "http://127.0.0.1:30000/v1", "gemma-4-26b-a4b-nvfp4": "http://127.0.0.1:30001/v1"},
    )
    monkeypatch.setattr(factory.config, "sglang_base_url_for_model", lambda model: factory.config.SGLANG_MODEL_ENDPOINTS.get(model, "http://127.0.0.1:30000/v1"))
    monkeypatch.setattr(factory, "_served_models_for_endpoint", lambda endpoint, api_key=None: ["gpt-oss-20b"] if endpoint.endswith("30000/v1") else [])
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)

    grouped = factory.list_available_models()

    assert grouped["sglang"] == ["gpt-oss-20b"]


def test_served_model_is_exposed_even_when_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(factory.config, "VLLM_DEFAULT_MODEL", "gemma-4-26b-a4b-nvfp4")
    monkeypatch.setattr(factory.config, "VLLM_CANDIDATE_MODELS", ["gemma-4-26b-a4b-nvfp4"])
    monkeypatch.setattr(factory.config, "VLLM_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "VLLM_BASE_URL", "http://127.0.0.1:30001/v1")
    monkeypatch.setattr(factory.config, "VLLM_STRICT_AVAILABLE_MODELS", False)
    monkeypatch.setattr(factory.config, "VLLM_DISABLED_MODELS", set())
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_DIR", Path("/missing"))
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["gpt-oss-20b"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)

    def fake_served(endpoint, api_key=None):
        if endpoint.endswith("30001/v1"):
            return ["nemotron-3-nano-30b-a3b-nvfp4"]
        return []

    monkeypatch.setattr(factory, "_served_models_for_endpoint", fake_served)

    grouped = factory.list_available_models()

    assert grouped["vllm"] == ["nemotron-3-nano-30b-a3b-nvfp4"]


def test_disabled_vllm_models_are_hidden_and_rejected(monkeypatch) -> None:
    monkeypatch.setattr(factory.config, "VLLM_DEFAULT_MODEL", "gemma-4-31b-it-nvfp4")
    monkeypatch.setattr(factory.config, "VLLM_CANDIDATE_MODELS", ["gemma-4-31b-it-nvfp4", "gemma-4-26b-a4b-nvfp4"])
    monkeypatch.setattr(factory.config, "VLLM_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "VLLM_BASE_URL", "http://127.0.0.1:30001/v1")
    monkeypatch.setattr(factory.config, "VLLM_STRICT_AVAILABLE_MODELS", False)
    monkeypatch.setattr(factory.config, "VLLM_DISABLED_MODELS", {"gemma-4-26b-a4b-nvfp4"})
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_DIR", Path("/missing"))
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["gpt-oss-20b"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)
    monkeypatch.setattr(factory, "_served_models_for_endpoint", lambda endpoint, api_key=None: ["gemma-4-26b-a4b-nvfp4"] if endpoint.endswith("30001/v1") else [])

    grouped = factory.list_available_models()

    assert grouped["vllm"] == ["gemma-4-31b-it-nvfp4"]
    with pytest.raises(RuntimeError, match="비활성화"):
        factory.build_llm("gemma-4-26b-a4b-nvfp4", provider="vllm")


def test_unknown_served_model_is_not_exposed(monkeypatch) -> None:
    monkeypatch.setattr(factory.config, "VLLM_DEFAULT_MODEL", "gemma-4-31b-it-nvfp4")
    monkeypatch.setattr(factory.config, "VLLM_CANDIDATE_MODELS", ["gemma-4-31b-it-nvfp4"])
    monkeypatch.setattr(factory.config, "VLLM_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "VLLM_BASE_URL", "http://127.0.0.1:30001/v1")
    monkeypatch.setattr(factory.config, "VLLM_STRICT_AVAILABLE_MODELS", True)
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_DIR", Path("/missing"))
    monkeypatch.setattr(factory.config, "SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
    monkeypatch.setattr(factory.config, "SGLANG_CANDIDATE_MODELS", ["gpt-oss-20b"])
    monkeypatch.setattr(factory.config, "SGLANG_MODEL_ENDPOINTS", {})
    monkeypatch.setattr(factory.config, "SGLANG_DISABLED_MODELS", set())
    monkeypatch.setenv("ALLOW_OLLAMA", "false")
    monkeypatch.setattr(factory.config, "OFFLINE_MODE", True)

    def fake_served(endpoint, api_key=None):
        if endpoint.endswith("30001/v1"):
            return ["unknown-local-model"]
        return []

    monkeypatch.setattr(factory, "_served_models_for_endpoint", fake_served)

    grouped = factory.list_available_models()

    assert grouped["vllm"] == []


def test_build_llm_rejects_unsupported_provider_models() -> None:
    with pytest.raises(RuntimeError, match="SGLang provider"):
        factory.build_llm("exaone-4.0-32b-awq", provider="sglang")

    with pytest.raises(RuntimeError, match="vLLM provider"):
        factory.build_llm("qwen3-next-80b-a3b-instruct-fp8", provider="vllm")


def test_extract_final_content_strips_pad_tokens() -> None:
    from src.llm.openai_compatible_client import _extract_final_content

    assert _extract_final_content("<pad><pad>완료<pad>") == "완료"
