"""모델 ID 패턴으로 적절한 LLMClient를 만든다."""

from __future__ import annotations

import os

from src import config
from src.llm.base import LLMClient
from src.llm.ollama_client import OllamaClient

OPENAI_MODEL_INFO: dict[str, dict] = {
    "gpt-5.2": {"family": "GPT-5.2", "size": "standard", "use_case": "고성능"},
    "gpt-5.2-pro": {"family": "GPT-5.2", "size": "pro", "use_case": "최고성능"},
    "gpt-5": {"family": "GPT-5", "size": "standard", "use_case": "고성능"},
    "gpt-5-mini": {"family": "GPT-5", "size": "mini", "use_case": "균형형"},
    "gpt-5-nano": {"family": "GPT-5", "size": "nano", "use_case": "저비용"},
    "gpt-4.1": {"family": "GPT-4.1", "size": "standard", "use_case": "고성능"},
    "gpt-4.1-mini": {"family": "GPT-4.1", "size": "mini", "use_case": "균형형"},
    "gpt-4.1-nano": {"family": "GPT-4.1", "size": "nano", "use_case": "저비용"},
    "gpt-4o": {"family": "GPT-4o", "size": "standard", "use_case": "호환"},
    "gpt-4o-mini": {"family": "GPT-4o", "size": "mini", "use_case": "저비용"},
}


def parse_openai_candidate_models(raw: str | None, default: list[str] | None = None) -> list[str]:
    """쉼표 구분 OpenAI 후보 모델 문자열을 리스트로 변환한다."""

    if raw is None or not raw.strip():
        return list(default or config.DEFAULT_OPENAI_CANDIDATE_MODELS)
    return [model.strip() for model in raw.split(",") if model.strip()]


def normalize_model_id(model: str) -> str:
    """provider prefix를 제거한 실제 모델 ID를 반환한다."""

    return model.removeprefix("openai:")


def is_openai_model(model: str) -> bool:
    """OpenAI 모델 ID인지 판정한다."""

    normalized = normalize_model_id(model)
    return normalized.startswith("gpt-")


def is_ollama_allowed() -> bool:
    """현재 환경에서 Ollama 모델 사용이 허용되는지 반환한다."""

    return os.getenv("ALLOW_OLLAMA", "true").lower() == "true"


def get_openai_model_info(model: str) -> dict:
    """OpenAI 모델 메타데이터를 반환한다."""

    normalized = normalize_model_id(model)
    if normalized in OPENAI_MODEL_INFO:
        return {"model": normalized, **OPENAI_MODEL_INFO[normalized]}
    parts = normalized.split("-")
    family = "-".join(parts[:2]).upper() if len(parts) >= 2 else normalized
    size = parts[-1] if parts[-1] in {"mini", "nano", "pro"} else "standard"
    return {"model": normalized, "family": family, "size": size, "use_case": "사용자 정의"}


def format_model_label(model: str, provider: str) -> str:
    """모델 선택 UI 표시 라벨을 만든다."""

    if provider == "openai" or is_openai_model(model):
        info = get_openai_model_info(model)
        suffix = f" {info['size']}" if info["size"] != "standard" else ""
        return f"Cloud · OpenAI · {info['family']}{suffix} · {info['use_case']}"
    return f"Local · Ollama · {model}"


def list_available_models() -> dict[str, list[str]]:
    """그룹별 모델 후보를 반환한다."""

    local: list[str] = []
    if is_ollama_allowed():
        try:
            installed = set(OllamaClient(config.OLLAMA_HOST, config.OLLAMA_MODEL).list_models())
            local = [model for model in config.OLLAMA_CANDIDATE_MODELS if model in installed]
            if config.OLLAMA_MODEL in installed and config.OLLAMA_MODEL not in local:
                local.insert(0, config.OLLAMA_MODEL)
        except Exception:
            local = []

    cloud = list(config.OPENAI_CANDIDATE_MODELS) if os.getenv("OPENAI_API_KEY", "") else []
    return {"local": local, "cloud": cloud}


def build_llm(model: str) -> LLMClient:
    """모델 ID에 맞는 LLMClient를 생성한다."""

    if is_openai_model(model):
        if not os.getenv("OPENAI_API_KEY", ""):
            raise RuntimeError("OpenAI 모델을 선택했지만 OPENAI_API_KEY가 설정되지 않았습니다.")
        from src.llm.openai_client import OpenAIClient

        return OpenAIClient(normalize_model_id(model))
    if not is_ollama_allowed():
        raise RuntimeError("현재 환경에서는 로컬(Ollama) 모델 사용이 비활성화되어 있습니다. OpenAI 모델을 선택해 주세요.")
    return OllamaClient(config.OLLAMA_HOST, model)
