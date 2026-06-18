from __future__ import annotations

from src.llm.factory import list_available_models, list_runtime_models


def test_gpt_oss_120b_is_not_selectable_on_dgx_spark(monkeypatch):
    monkeypatch.setenv("INSURANCE_RAG_RUNTIME_PROFILE", "dgx_spark")

    models = list_runtime_models(provider="trtllm", include_diagnostics=True)
    target = next(model for model in models if model["id"] == "openai/gpt-oss-120b")

    assert target["status"] == "unsupported_on_dgx_spark"
    assert target["selectable"] is False
    assert "DGX Spark" in target["reason"]


def test_trtllm_120b_is_excluded_even_if_endpoint_advertises_it(monkeypatch):
    monkeypatch.setattr("src.llm.factory._served_models_for_endpoint", lambda endpoint, api_key=None: ["openai/gpt-oss-120b"])
    monkeypatch.setattr("src.llm.factory.config.TRTLLM_DEFAULT_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr("src.llm.factory.config.TRTLLM_CANDIDATE_MODELS", ["openai/gpt-oss-120b"])
    monkeypatch.setattr("src.llm.factory.config.TRTLLM_DISABLED_MODELS", set())
    monkeypatch.setattr("src.llm.factory.config.TRTLLM_STRICT_AVAILABLE_MODELS", True)
    monkeypatch.setenv("ALLOW_OLLAMA", "false")

    grouped = list_available_models()

    assert grouped["trtllm"] == []


def test_selectable_runtime_models_hide_unsupported_120b():
    selectable = list_runtime_models(provider="trtllm", include_diagnostics=False)

    assert all(model["id"] != "openai/gpt-oss-120b" for model in selectable)
