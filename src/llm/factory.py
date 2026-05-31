"""LLM provider routing and display helpers."""

from __future__ import annotations

import os
from collections import OrderedDict

import requests

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
    "vllm": "Local · vLLM",
    "ollama": "Local · Ollama",
    "openai": "Cloud · OpenAI",
}

LOCAL_LARGE_MODEL_INFO: dict[str, dict[str, str]] = {
    "gemma-4-26b-a4b-nvfp4": {
        "family": "Gemma 4",
        "size": "26B A4B NVFP4",
        "status": "validated",
        "use_case": "vLLM 로컬 답변",
    },
    "gemma-4-31b-it-nvfp4": {
        "family": "Gemma 4",
        "size": "31B IT NVFP4",
        "status": "staged",
        "use_case": "vLLM 고성능 로컬 답변",
    },
    "nemotron-3-nano-30b-a3b-nvfp4": {
        "family": "Nemotron 3 Nano",
        "size": "30B A3B NVFP4",
        "status": "staged",
        "use_case": "vLLM 신규 비교 모델",
    },
}

SGLANG_MODEL_INFO: dict[str, dict[str, str]] = {
    "gpt-oss-20b": {
        "family": "GPT-OSS",
        "size": "20B",
        "status": "validated",
        "use_case": "기본 로컬 답변",
    },
    "gemma-4-26b-a4b-nvfp4": {
        "family": "Gemma 4",
        "size": "26B A4B NVFP4",
        "status": "disabled",
        "use_case": "SGLang 비활성: NVFP4/vLLM 후보",
    },
    "qwen3-30b-a3b-instruct-2507-fp8": {
        "family": "Qwen3 Instruct",
        "size": "30B A3B FP8",
        "status": "staged",
        "use_case": "SGLang 신규 비교 모델",
    },
    "qwen3-next-80b-a3b-instruct-fp8": {
        "family": "Qwen3 Next Instruct",
        "size": "80B A3B FP8",
        "status": "staged",
        "use_case": "SGLang 장문/고성능 비교 모델",
    },
    "qwen3-next-80b-a3b-thinking-fp8": {
        "family": "Qwen3 Next Thinking",
        "size": "80B A3B FP8",
        "status": "staged",
        "use_case": "SGLang 추론형 비교 모델",
    },
}


def _ordered_unique(items: list[str]) -> list[str]:
    """Return items without duplicates while preserving order."""

    return list(OrderedDict((item, None) for item in items if item).keys())


def _discover_local_sglang_models() -> list[str]:
    """Discover locally staged SGLang model directories."""

    model_dir = config.SGLANG_MODEL_DIR
    if not model_dir.exists():
        return []
    discovered: list[str] = []
    for child in sorted(model_dir.iterdir()):
        if not child.is_dir():
            continue
        if (child / "config.json").exists() and (child / "tokenizer.json").exists():
            discovered.append(child.name)
    return discovered


def is_sglang_model_disabled(model: str) -> bool:
    """Return whether a staged model is blocked for the current SGLang runtime."""

    return normalize_model_id(model) in config.SGLANG_DISABLED_MODELS


def _configured_sglang_models() -> list[str]:
    """Return all configured or locally staged SGLang model names."""

    candidates = _ordered_unique(
        [config.SGLANG_DEFAULT_MODEL]
        + list(config.SGLANG_CANDIDATE_MODELS)
        + list(config.SGLANG_MODEL_ENDPOINTS.keys())
        + _discover_local_sglang_models()
    )
    return [model for model in candidates if not is_sglang_model_disabled(model)]


def _served_models_for_endpoint(base_url: str, api_key: str | None = None) -> list[str]:
    """Return model IDs advertised by an OpenAI-compatible endpoint."""

    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = requests.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=1.5)
        response.raise_for_status()
    except requests.RequestException:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    models = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        if model_id:
            models.append(model_id)
    return models


def _served_models_by_endpoint(endpoints: list[str], api_key: str | None = None) -> dict[str, list[str]]:
    """Return OpenAI-compatible /models results keyed by normalized endpoint."""

    served: dict[str, list[str]] = {}
    for endpoint in _ordered_unique([endpoint.rstrip("/") for endpoint in endpoints if endpoint]):
        served[endpoint] = _served_models_for_endpoint(endpoint, api_key=api_key)
    return served


def list_sglang_large_models() -> list[str]:
    """Return configured large SGLang models, including staged local assets."""

    return _configured_sglang_models()


def list_vllm_large_models() -> list[str]:
    """Return configured large vLLM models."""

    return _ordered_unique([config.VLLM_DEFAULT_MODEL] + list(config.VLLM_CANDIDATE_MODELS) + list(config.VLLM_MODEL_ENDPOINTS.keys()))


def _available_vllm_models() -> list[str]:
    """Return vLLM models exposed in the UI."""

    candidates = list_vllm_large_models()
    endpoints = [config.VLLM_BASE_URL, *config.VLLM_MODEL_ENDPOINTS.values(), *[config.vllm_base_url_for_model(model) for model in candidates]]
    served_by_endpoint = _served_models_by_endpoint(endpoints, api_key=config.VLLM_API_KEY)
    served_models = _ordered_unique([model for models in served_by_endpoint.values() for model in models])
    if not served_models and not config.VLLM_STRICT_AVAILABLE_MODELS:
        return candidates

    candidates = _ordered_unique(candidates + served_models)

    available: list[str] = []
    for model in candidates:
        served = served_by_endpoint.get(config.vllm_base_url_for_model(model), [])
        if model in served:
            available.append(model)
    return _ordered_unique(available)


def list_startup_large_models() -> list[tuple[str, str]]:
    """Return provider/model pairs that can be loaded as the login-time large model."""

    return [("sglang", model) for model in list_sglang_large_models()] + [("vllm", model) for model in list_vllm_large_models()]


def _available_sglang_models() -> list[str]:
    """Return SGLang models that should be exposed in the UI."""

    candidates = _configured_sglang_models()
    endpoints = [config.SGLANG_BASE_URL, *config.SGLANG_MODEL_ENDPOINTS.values(), *[config.sglang_base_url_for_model(model) for model in candidates]]
    served_by_endpoint = _served_models_by_endpoint(endpoints, api_key=config.SGLANG_API_KEY)
    served_models = _ordered_unique(
        [
            model
            for models in served_by_endpoint.values()
            for model in models
            if not is_sglang_model_disabled(model)
        ]
    )
    if not served_models and not config.SGLANG_STRICT_AVAILABLE_MODELS:
        return candidates

    candidates = _ordered_unique(candidates + served_models)

    available: list[str] = []
    for model in candidates:
        served = served_by_endpoint.get(config.sglang_base_url_for_model(model), [])
        if model in served:
            available.append(model)
    return _ordered_unique(available)



def parse_openai_candidate_models(raw: str | None, default: list[str] | None = None) -> list[str]:
    """Convert comma-separated OpenAI candidate model text to a list."""

    if raw is None or not raw.strip():
        return list(default or config.DEFAULT_OPENAI_CANDIDATE_MODELS)
    return [model.strip() for model in raw.split(",") if model.strip()]


def normalize_model_id(model: str) -> str:
    """Remove known provider prefixes from a model ID."""

    for prefix in ("openai:", "sglang:", "vllm:", "ollama:"):
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
    if normalized.startswith("gpt-") and normalized not in list_sglang_large_models():
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
    return normalized.startswith("gpt-") and normalized not in list_sglang_large_models()


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
        info = SGLANG_MODEL_INFO.get(normalized)
        if info:
            status_labels = {"validated": "검증완료", "staged": "검증대상", "disabled": "비활성"}
            status = status_labels.get(info["status"], "검증대상")
            return f"Local · SGLang · {info['family']} · {info['size']} · {status}"
        return f"Local · SGLang · {normalized}"
    if provider == "vllm":
        info = LOCAL_LARGE_MODEL_INFO.get(normalized, SGLANG_MODEL_INFO.get(normalized))
        if info:
            status_labels = {"validated": "검증완료", "staged": "검증대상", "disabled": "비활성"}
            status = status_labels.get(info["status"], "검증대상")
            return f"Local · vLLM · {info['family']} · {info['size']} · {status}"
        return f"Local · vLLM · {normalized}"
    return f"Local · Ollama · {normalized}"


def list_available_models() -> dict[str, list[str]]:
    """Return model candidates grouped by provider."""

    grouped: dict[str, list[str]] = {"sglang": _available_sglang_models(), "vllm": _available_vllm_models(), "ollama": [], "openai": []}
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
        if is_sglang_model_disabled(selected_model):
            raise RuntimeError(
                f"{selected_model} 모델은 현재 SGLang 런타임에서 비활성화되어 있습니다. "
                "직접 생성 테스트에서 <pad> 반복이 발생했으므로 gpt-oss-20b 또는 별도 vLLM 검증 경로를 사용하세요."
            )
        from src.llm.openai_compatible_client import OpenAICompatibleClient

        return OpenAICompatibleClient(selected_model)
    if selected_provider == "vllm":
        from src.llm.openai_compatible_client import OpenAICompatibleClient

        return OpenAICompatibleClient(
            selected_model,
            base_url=config.vllm_base_url_for_model(selected_model),
            api_key=config.VLLM_API_KEY,
            provider="vllm",
        )
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
