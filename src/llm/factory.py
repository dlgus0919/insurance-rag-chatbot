"""LLM provider routing and display helpers."""

from __future__ import annotations

import os

from src import config
from src.llm.base import LLMClient
from src.llm.ollama_client import OllamaClient

Provider = str

OPENAI_MODEL_INFO: dict[str, dict] = {
    "gpt-5.5": {"family": "GPT-5.5", "size": "standard", "use_case": "최고품질"},
    "gpt-5.2-chat-latest": {"family": "GPT-5.2", "size": "standard", "use_case": "고성능"},
    "gpt-5.4-mini": {"family": "GPT-5.4", "size": "mini", "use_case": "고속/균형"},
    "gpt-5-mini": {"family": "GPT-5", "size": "mini", "use_case": "경량/저비용"},
}
PROVIDER_LABELS: dict[str, str] = {
    "sglang": "Local · SGLang",
    "ollama": "Local · Ollama",
    "openai": "Cloud · OpenAI",
}


def parse_openai_candidate_models(raw: str | None, default: list[str] | None = None) -> list[str]:
    """Convert comma-separated OpenAI candidate model text to a list."""

    if raw is None or not raw.strip():
        return list(default or config.DEFAULT_OPENAI_CANDIDATE_MODELS)
    return [model.strip() for model in raw.split(",") if model.strip()]


def normalize_model_id(model: str) -> str:
    """Remove known provider prefixes from a model ID."""

    for prefix in ("openai:", "sglang:", "ollama:"):
        if model.startswith(prefix):
            return model.removeprefix(prefix)
    return model


def provider_prefixed_model(provider: str, model: str) -> str:
    """Return a stable provider-prefixed selection ID."""

    return f"{provider}:{normalize_model_id(model)}"


def split_model_selection(selection: str, default_provider: str | None = None) -> tuple[str, str]:
    """Split a UI/model selection into provider and model."""

    if ":" in selection:
        provider, model = selection.split(":", 1)
        if provider in PROVIDER_LABELS:
            return provider, model
    if default_provider is not None:
        return default_provider, normalize_model_id(selection)
    normalized = normalize_model_id(selection)
    if normalized.startswith("gpt-") and normalized not in config.SGLANG_CANDIDATE_MODELS:
        return "openai", normalized
    return "ollama", selection


def is_openai_model(model: str) -> bool:
    """Return whether the model ID looks like an OpenAI cloud model."""

    if ":" in model:
        provider, raw_model = model.split(":", 1)
        if provider in PROVIDER_LABELS:
            return provider == "openai"
        normalized = model
    else:
        normalized = normalize_model_id(model)
    return normalized.startswith("gpt-") and normalized not in config.SGLANG_CANDIDATE_MODELS


def is_ollama_allowed() -> bool:
    """Return whether Ollama models are allowed."""

    return os.getenv("ALLOW_OLLAMA", "true").lower() == "true"


def is_cloud_allowed() -> bool:
    """Return whether external cloud LLMs are allowed."""

    return not config.OFFLINE_MODE


def get_openai_model_info(model: str) -> dict:
    """Return OpenAI model metadata for display."""

    normalized = normalize_model_id(model)
    if normalized in OPENAI_MODEL_INFO:
        return {"model": normalized, **OPENAI_MODEL_INFO[normalized]}
    parts = normalized.split("-")
    family = "-".join(parts[:2]).upper() if len(parts) >= 2 else normalized
    size = parts[-1] if parts[-1] in {"mini", "nano", "pro"} else "standard"
    return {"model": normalized, "family": family, "size": size, "use_case": "사용자 정의"}


def format_model_label(model: str, provider: str) -> str:
    """Return a display label for a provider/model pair."""

    normalized = normalize_model_id(model)
    if provider == "openai":
        info = get_openai_model_info(normalized)
        suffix = f" {info['size']}" if info["size"] != "standard" else ""
        return f"Cloud · OpenAI · {info['family']}{suffix} · {info['use_case']}"
    if provider == "sglang":
        return f"Local · SGLang · {normalized}"
    return f"Local · Ollama · {normalized}"


def list_available_models() -> dict[str, list[str]]:
    """Return model candidates grouped by provider."""

    grouped: dict[str, list[str]] = {"sglang": list(config.SGLANG_CANDIDATE_MODELS), "ollama": [], "openai": []}
    if is_ollama_allowed():
        try:
            installed = set(OllamaClient(config.OLLAMA_HOST, config.OLLAMA_MODEL).list_models())
            grouped["ollama"] = [model for model in config.OLLAMA_CANDIDATE_MODELS if model in installed]
            if config.OLLAMA_MODEL in installed and config.OLLAMA_MODEL not in grouped["ollama"]:
                grouped["ollama"].insert(0, config.OLLAMA_MODEL)
        except Exception:
            grouped["ollama"] = []
    if is_cloud_allowed() and os.getenv("OPENAI_API_KEY", ""):
        grouped["openai"] = list(config.OPENAI_CANDIDATE_MODELS)
    return grouped


def build_llm(model: str, provider: str | None = None) -> LLMClient:
    """Build an LLM client for the selected provider/model."""

    selected_provider, selected_model = split_model_selection(model, provider)
    if selected_provider == "sglang":
        from src.llm.openai_compatible_client import OpenAICompatibleClient

        return OpenAICompatibleClient(selected_model)
    if selected_provider == "openai":
        if config.OFFLINE_MODE:
            raise RuntimeError("OFFLINE_MODE=true에서는 OpenAI Cloud 모델을 사용할 수 없습니다.")
        if not os.getenv("OPENAI_API_KEY", ""):
            raise RuntimeError("OpenAI 모델을 선택했지만 OPENAI_API_KEY가 설정되지 않았습니다.")
        from src.llm.openai_client import OpenAIClient

        return OpenAIClient(selected_model)
    if not is_ollama_allowed():
        raise RuntimeError("현재 환경에서는 Ollama 모델 사용이 비활성화되어 있습니다. 다른 provider를 선택해 주세요.")
    return OllamaClient(config.OLLAMA_HOST, selected_model)
