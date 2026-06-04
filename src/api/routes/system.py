"""System health and model discovery routes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from src import config
from src.api.schemas.system import HealthResponse, ModelInfo, ModelListResponse, SystemStatusResponse
from src.llm.factory import format_model_label, list_runtime_available_models as _list_runtime_available_models
from src.retrieval.index_mode import resolve_index_paths

router = APIRouter(tags=["system"])


def list_available_models() -> dict[str, list[str]]:
    """Backward-compatible model discovery hook used by older route tests."""

    return _list_runtime_available_models()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Load balancer friendly health endpoint."""

    return HealthResponse(status="ok")


@router.get("/system/models", response_model=ModelListResponse)
async def models() -> ModelListResponse:
    """Return provider-grouped model choices that are callable right now."""

    grouped = list_available_models()
    local = []

    # Backward-compatible shape used by earlier SPA tests and lightweight mocks.
    for model in grouped.get("local", []):
        local.append(ModelInfo(provider="local", id=model, label=model))

    # 1. SGLang models
    for model in grouped.get("sglang", []):
        prefixed_id = f"sglang:{model}"
        label = format_model_label(model, "sglang")
        local.append(ModelInfo(provider="local", id=prefixed_id, label=label))

    # 2. vLLM models
    for model in grouped.get("vllm", []):
        prefixed_id = f"vllm:{model}"
        label = format_model_label(model, "vllm")
        local.append(ModelInfo(provider="local", id=prefixed_id, label=label))

    # 3. Ollama models
    for model in grouped.get("ollama", []):
        prefixed_id = f"ollama:{model}"
        label = format_model_label(model, "ollama")
        local.append(ModelInfo(provider="local", id=prefixed_id, label=label))

    openai = []
    for model in grouped.get("cloud", []):
        openai.append(ModelInfo(provider="openai", id=model, label=model))

    # 4. OpenAI models
    for model in grouped.get("openai", []):
        prefixed_id = f"openai:{model}"
        label = format_model_label(model, "openai")
        openai.append(ModelInfo(provider="openai", id=prefixed_id, label=label))

    # Determine defaults
    local_default = None
    for prefix, model_id in [("vllm", config.VLLM_DEFAULT_MODEL), ("sglang", config.SGLANG_DEFAULT_MODEL), ("ollama", config.OLLAMA_MODEL)]:
        pref = f"{prefix}:{model_id}"
        if any(m.id == pref for m in local):
            local_default = pref
            break
    if local and local_default is None:
        local_default = local[0].id

    openai_default = None
    pref_openai = f"openai:{config.OPENAI_DEFAULT_MODEL}"
    if any(m.id == pref_openai for m in openai):
        openai_default = pref_openai
    if openai and openai_default is None:
        openai_default = openai[0].id

    return ModelListResponse(
        providers={"local": local, "openai": openai},
        defaults={"local": local_default, "openai": openai_default},
    )


@router.get("/system/status", response_model=SystemStatusResponse)
async def status() -> SystemStatusResponse:
    """Report basic backend asset availability."""

    default_bm25, default_chroma = resolve_index_paths("default")
    v2_bm25, v2_chroma = resolve_index_paths("v2_only")
    combined_bm25, combined_chroma = resolve_index_paths("v1_v2_combined")
    users_path = Path(os.getenv("USERS_JSON_PATH", str(config.ROOT_DIR / "users.json")))

    paths = {
        "chunks": config.CHUNKS_PATH.exists(),
        "bm25": default_bm25.exists(),
        "chroma": default_chroma.exists(),
        "bm25_v2_only": v2_bm25.exists(),
        "chroma_v2_only": v2_chroma.exists(),
        "bm25_v1_v2_combined": combined_bm25.exists(),
        "chroma_v1_v2_combined": combined_chroma.exists(),
        "graph": config.GRAPH_INDEX_PATH.exists(),
        "relational": config.STANDARD_CODES_DB_PATH.exists(),
        "users": users_path.exists(),
    }
    overall = "ok" if any(paths.values()) else "degraded"
    return SystemStatusResponse(status=overall, paths=paths)
