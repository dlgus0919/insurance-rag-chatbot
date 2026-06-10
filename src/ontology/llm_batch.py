from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_MODEL_PRIORITY = (
    "qwen3-next-80b-a3b-instruct-fp8",
    "qwen3-30b-a3b-instruct-2507-fp8",
    "gpt-oss-20b",
)
SGLANG_MODELS = set(DEFAULT_MODEL_PRIORITY)
VLLM_MODELS: set[str] = set()


@dataclass(frozen=True)
class LlmBatchConfig:
    llm: str = "none"
    model: str | None = None
    start_llm: bool = False
    stop_llm_after: bool = False
    llm_base_url: str | None = None
    timeout: int = 1800
    switch_sglang_script: Path = Path("/srv/ai-ops/bin/switch-sglang-model")
    switch_vllm_script: Path = Path("/srv/ai-ops/bin/switch-vllm-model")
    model_priority: tuple[str, ...] = field(default_factory=lambda: DEFAULT_MODEL_PRIORITY)


@dataclass(frozen=True)
class LlmBatchSelection:
    provider: str
    model: str
    base_url: str
    switch_script: Path


def select_batch_model(config: LlmBatchConfig) -> LlmBatchSelection:
    model = config.model or config.model_priority[0]
    if config.llm == "vllm" or model in VLLM_MODELS:
        provider = "vllm"
        base_url = config.llm_base_url or "http://127.0.0.1:30001/v1"
        script = config.switch_vllm_script
    else:
        provider = "sglang"
        base_url = config.llm_base_url or "http://127.0.0.1:30000/v1"
        script = config.switch_sglang_script
    return LlmBatchSelection(provider=provider, model=model, base_url=base_url, switch_script=script)


def maybe_start_llm_server(config: LlmBatchConfig, *, dry_run: bool = False) -> LlmBatchSelection | None:
    if config.llm == "none":
        return None
    selection = select_batch_model(config)
    if not config.start_llm or dry_run:
        return selection
    subprocess.run([str(selection.switch_script), selection.model], check=True, timeout=config.timeout)
    return selection


def maybe_stop_llm_server(config: LlmBatchConfig, selection: LlmBatchSelection | None, *, dry_run: bool = False) -> None:
    if not config.stop_llm_after or selection is None or dry_run:
        return
    if selection.provider == "sglang":
        subprocess.run(["tmux", "kill-session", "-t", "sglang-local"], check=False)
    elif selection.provider == "vllm":
        subprocess.run(["tmux", "kill-session", "-t", "vllm-gemma4"], check=False)
