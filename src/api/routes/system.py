"""System health and model discovery routes."""

from __future__ import annotations

from fastapi import APIRouter

from src import config
from src.api.schemas.system import HealthResponse, ModelInfo, ModelListResponse, SystemStatusResponse
from src.llm.factory import format_model_label, list_available_models

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Load balancer friendly health endpoint."""

    return HealthResponse(status="ok")


@router.get("/system/models", response_model=ModelListResponse)
async def models() -> ModelListResponse:
    """Return provider-grouped model choices from env and Ollama state."""

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

    paths = {
        "chunks": config.get_ingest_paths(config.DEFAULT_OCR_VERSION)["chunks_path"].exists(),
        "bm25": config.get_ingest_paths(config.DEFAULT_OCR_VERSION)["bm25_path"].exists(),
        "chroma": config.get_ingest_paths(config.DEFAULT_OCR_VERSION)["chroma_dir"].exists(),
        "bm25_v2_only": config.get_ingest_paths("v2_manual")["bm25_path"].exists(),
        "chroma_v2_only": config.get_ingest_paths("v2_manual")["chroma_dir"].exists(),
        "bm25_v1_v2_combined": config.get_ingest_paths("v1_v2_combined")["bm25_path"].exists(),
        "chroma_v1_v2_combined": config.get_ingest_paths("v1_v2_combined")["chroma_dir"].exists(),
        "graph": config.GRAPH_INDEX_PATH.exists(),
        "relational": config.RELATIONAL_INDEX_DIR.exists(),
        "users": config.ROOT_DIR.joinpath("users.json").exists(),
    }
    overall = "ok" if any(paths.values()) else "degraded"
    return SystemStatusResponse(status=overall, paths=paths)
