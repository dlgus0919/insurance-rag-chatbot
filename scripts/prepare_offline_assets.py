#!/usr/bin/env python3
"""Prepare all model assets required for DGX offline chatbot execution.

This script downloads Hugging Face assets while the DGX has network access,
stores them under /srv/ai-ops, writes an offline runtime env file, and verifies
that embedding/reranker models can be loaded with HF offline flags enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SnapshotAsset:
    name: str
    repo_id: str
    target: Path
    required_files: tuple[str, ...]
    handoff_sources: tuple[Path, ...] = field(default_factory=tuple)


@dataclass
class AssetResult:
    name: str
    repo_id: str
    target: str
    status: str
    required_files_present: dict[str, bool]
    error: str | None = None


DEFAULT_ROOT = Path("/srv/ai-ops")
DEFAULT_ENV_PATH = DEFAULT_ROOT / "secrets" / "insurance-rag-chatbot" / "offline.env"
DEFAULT_MANIFEST_PATH = DEFAULT_ROOT / "manifests" / "insurance-rag-offline-assets.json"
DEFAULT_PROJECT_DIR = Path("/srv/shared/projects/insurance-rag-chatbot")
DEFAULT_HANDOFF_DIR = DEFAULT_PROJECT_DIR / "handoff"


def _asset_plan(root: Path) -> list[SnapshotAsset]:
    return [
        SnapshotAsset(
            name="embedding",
            repo_id="BAAI/bge-m3",
            target=root / "models" / "embedding" / "bge-m3",
            required_files=("config.json", "modules.json"),
        ),
        SnapshotAsset(
            name="reranker",
            repo_id="BAAI/bge-reranker-v2-m3",
            target=root / "models" / "reranker" / "bge-reranker-v2-m3",
            required_files=("config.json",),
        ),
        SnapshotAsset(
            name="llm_gpt_oss",
            repo_id="openai/gpt-oss-20b",
            target=root / "llm" / "models" / "gpt-oss-20b",
            required_files=("config.json", "tokenizer.json"),
        ),
        SnapshotAsset(
            name="llm_gemma4_nvfp4",
            repo_id="nvidia/Gemma-4-26B-A4B-NVFP4",
            target=root / "llm" / "models" / "gemma-4-26b-a4b-nvfp4",
            required_files=("config.json", "tokenizer.json", "model.safetensors.index.json", "chat_template.jinja", "hf_quant_config.json"),
            handoff_sources=(
                DEFAULT_HANDOFF_DIR / "llm_stage1_20260519" / "downloads" / "models" / "Gemma-4-26B-A4B-NVFP4",
            ),
        ),
    ]



def _required_status_at(path: Path, required_files: tuple[str, ...]) -> dict[str, bool]:
    return {name: (path / name).exists() for name in required_files}


def _promote_handoff_snapshot(asset: SnapshotAsset, force: bool) -> AssetResult | None:
    """Copy a complete handoff snapshot into the DGX runtime model directory."""

    if force:
        return None
    for source in asset.handoff_sources:
        source_status = _required_status_at(source, asset.required_files)
        if not all(source_status.values()):
            continue
        asset.target.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(
                source,
                asset.target,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("._*", ".DS_Store"),
            )
        except OSError as exc:
            return AssetResult(
                name=asset.name,
                repo_id=asset.repo_id,
                target=str(asset.target),
                status="failed",
                required_files_present=_required_status(asset),
                error=f"failed to promote handoff source {source}: {exc}",
            )
        promoted_status = _required_status(asset)
        return AssetResult(
            name=asset.name,
            repo_id=asset.repo_id,
            target=str(asset.target),
            status="promoted_handoff" if all(promoted_status.values()) else "incomplete",
            required_files_present=promoted_status,
            error=None if all(promoted_status.values()) else f"handoff promotion incomplete from {source}",
        )
    return None

def _required_status(asset: SnapshotAsset) -> dict[str, bool]:
    return {name: (asset.target / name).exists() for name in asset.required_files}


def _download_snapshot(asset: SnapshotAsset, force: bool) -> AssetResult:
    asset.target.mkdir(parents=True, exist_ok=True)
    before = _required_status(asset)
    if not force and all(before.values()):
        return AssetResult(
            name=asset.name,
            repo_id=asset.repo_id,
            target=str(asset.target),
            status="skipped_existing",
            required_files_present=before,
        )

    promoted = _promote_handoff_snapshot(asset, force=force)
    if promoted is not None and promoted.status != "failed":
        return promoted

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        return AssetResult(
            name=asset.name,
            repo_id=asset.repo_id,
            target=str(asset.target),
            status="failed",
            required_files_present=before,
            error=f"huggingface_hub is not installed: {exc}",
        )

    try:
        snapshot_download(repo_id=asset.repo_id, local_dir=str(asset.target))
    except Exception as exc:  # pragma: no cover - network/environment dependent
        return AssetResult(
            name=asset.name,
            repo_id=asset.repo_id,
            target=str(asset.target),
            status="failed",
            required_files_present=_required_status(asset),
            error=str(exc),
        )

    after = _required_status(asset)
    status = "downloaded" if all(after.values()) else "incomplete"
    return AssetResult(
        name=asset.name,
        repo_id=asset.repo_id,
        target=str(asset.target),
        status=status,
        required_files_present=after,
        error=None if status == "downloaded" else "required files are missing after download",
    )


def _download_gpt_oss_template(root: Path, force: bool) -> AssetResult:
    target = root / "llm" / "templates" / "gpt_oss_harmony.jinja"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0 and not force:
        return AssetResult(
            name="gpt_oss_chat_template",
            repo_id="openai/gpt-oss-20b:chat_template.jinja",
            target=str(target),
            status="skipped_existing",
            required_files_present={target.name: True},
        )

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        return AssetResult(
            name="gpt_oss_chat_template",
            repo_id="openai/gpt-oss-20b:chat_template.jinja",
            target=str(target),
            status="failed",
            required_files_present={target.name: target.exists()},
            error=f"huggingface_hub is not installed: {exc}",
        )

    try:
        downloaded = hf_hub_download(repo_id="openai/gpt-oss-20b", filename="chat_template.jinja")
        target.write_text(Path(downloaded).read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as exc:  # pragma: no cover - network/environment dependent
        return AssetResult(
            name="gpt_oss_chat_template",
            repo_id="openai/gpt-oss-20b:chat_template.jinja",
            target=str(target),
            status="failed",
            required_files_present={target.name: target.exists()},
            error=str(exc),
        )

    present = target.exists() and target.stat().st_size > 0
    return AssetResult(
        name="gpt_oss_chat_template",
        repo_id="openai/gpt-oss-20b:chat_template.jinja",
        target=str(target),
        status="downloaded" if present else "incomplete",
        required_files_present={target.name: present},
        error=None if present else "template file is empty or missing",
    )


def _write_offline_env(root: Path, env_path: Path) -> dict[str, str]:
    values = {
        "OFFLINE_MODE": "true",
        "HF_MODEL_DOWNLOAD": "false",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "EMBEDDING_MODEL": str(root / "models" / "embedding" / "bge-m3"),
        "RERANKER_MODEL": str(root / "models" / "reranker" / "bge-reranker-v2-m3"),
        "RERANKER_ENABLED": "true",
        "SGLANG_BASE_URL": "http://127.0.0.1:30000/v1",
        "SGLANG_API_KEY": "EMPTY",
        "SGLANG_DEFAULT_MODEL": "gpt-oss-20b",
        "SGLANG_REASONING_EFFORT": "low",
        "SGLANG_CANDIDATE_MODELS": "gpt-oss-20b,gemma-4-26b-a4b-nvfp4",
        "SGLANG_MODEL_ENDPOINTS": "",
        "SGLANG_STRICT_AVAILABLE_MODELS": "true",
        "SGLANG_ENABLE_APP_SWITCH": "true",
        "SGLANG_SWITCH_SCRIPT": "/srv/ai-ops/bin/switch-sglang-model",
        "SGLANG_SWITCH_TIMEOUT": "900",
        "LOCAL_LLM_PROVIDER": "sglang",
        "ALLOW_OLLAMA": "true",
        "OLLAMA_HOST": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": "exaone3.5:7.8b",
        "OLLAMA_CANDIDATE_MODELS": "exaone3.5:7.8b",
    }
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# DGX offline runtime defaults for insurance-rag-chatbot.",
        "# Generated by scripts/prepare_offline_assets.py.",
        "# This file contains no secrets; env.sh may still hold private credentials.",
    ]
    lines.extend(f"{key}={value}" for key, value in values.items())
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env_path, 0o600)
    return values


def _run_verify(cmd: list[str], env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=180)
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
        "ok": proc.returncode == 0,
    }


def _verify_offline_loads(root: Path, project_dir: Path, no_verify_load: bool) -> dict[str, Any]:
    if no_verify_load:
        return {"skipped": True, "reason": "--no-verify-load"}

    python = project_dir / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)

    base_env = os.environ.copy()
    base_env.update(
        {
            "CUDA_VISIBLE_DEVICES": "",
            "OFFLINE_MODE": "true",
            "HF_MODEL_DOWNLOAD": "false",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "EMBEDDING_MODEL": str(root / "models" / "embedding" / "bge-m3"),
            "RERANKER_MODEL": str(root / "models" / "reranker" / "bge-reranker-v2-m3"),
        }
    )

    embedding_code = """
from sentence_transformers import SentenceTransformer
model = SentenceTransformer(r'%s', local_files_only=True)
vec = model.encode(['보험금 지급 기준 테스트'], normalize_embeddings=True)
print('embedding_load_ok', vec.shape)
""" % (root / "models" / "embedding" / "bge-m3")

    reranker_code = """
from sentence_transformers import CrossEncoder
model = CrossEncoder(r'%s', max_length=512, local_files_only=True)
scores = model.predict([('보험금 지급 기준', '보험 약관의 보상 기준 문장')])
print('reranker_load_ok', len(scores))
""" % (root / "models" / "reranker" / "bge-reranker-v2-m3")

    return {
        "embedding": _run_verify([str(python), "-c", embedding_code], base_env),
        "reranker": _run_verify([str(python), "-c", reranker_code], base_env),
    }


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and verify DGX offline runtime assets.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--env-path", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--project-dir", type=Path, default=DEFAULT_PROJECT_DIR)
    parser.add_argument("--force", action="store_true", help="Re-download assets even when required files exist.")
    parser.add_argument("--skip-llm", action="store_true", help="Skip all LLM snapshot downloads/verification.")
    parser.add_argument("--no-verify-load", action="store_true", help="Skip local_files_only load checks.")
    args = parser.parse_args()

    root = args.root
    assets = _asset_plan(root)
    if args.skip_llm:
        assets = [asset for asset in assets if not asset.name.startswith("llm_")]

    print(f"[INFO] offline asset root: {root}", flush=True)
    results: list[AssetResult] = []
    for asset in assets:
        print(f"[INFO] preparing {asset.name}: {asset.repo_id} -> {asset.target}", flush=True)
        result = _download_snapshot(asset, force=args.force)
        print(f"[INFO] {asset.name}: {result.status}", flush=True)
        if result.error:
            print(f"[WARN] {asset.name}: {result.error}", flush=True)
        results.append(result)

    print("[INFO] preparing GPT-OSS Harmony chat template", flush=True)
    template_result = _download_gpt_oss_template(root, force=args.force)
    print(f"[INFO] gpt_oss_chat_template: {template_result.status}", flush=True)
    if template_result.error:
        print(f"[WARN] gpt_oss_chat_template: {template_result.error}", flush=True)
    results.append(template_result)

    env_values = _write_offline_env(root, args.env_path)
    print(f"[INFO] wrote offline env: {args.env_path}", flush=True)

    verify = _verify_offline_loads(root, args.project_dir, args.no_verify_load)
    if isinstance(verify, dict):
        for name, item in verify.items():
            if isinstance(item, dict) and "ok" in item:
                print(f"[INFO] verify {name}: {'PASS' if item['ok'] else 'FAIL'}", flush=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "env_path": str(args.env_path),
        "offline_env": env_values,
        "assets": [asdict(result) for result in results],
        "verification": verify,
    }
    _write_manifest(args.manifest_path, payload)
    print(f"[INFO] wrote manifest: {args.manifest_path}", flush=True)

    failed = [result for result in results if result.status in {"failed", "incomplete"}]
    verify_failed = any(
        isinstance(item, dict) and item.get("ok") is False for item in verify.values()
    ) if isinstance(verify, dict) else False
    if failed or verify_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
