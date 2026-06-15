#!/usr/bin/env python3
"""Run answer-generation model evals one model at a time with cleanup checks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS = [
    "sglang:gpt-oss-20b",
    "sglang:qwen3-30b-a3b-instruct-2507-fp8",
    "sglang:qwen3-next-80b-a3b-instruct-fp8",
    "sglang:qwen3-next-80b-a3b-thinking-fp8",
    "vllm:gemma-4-26b-a4b-nvfp4",
    "vllm:gemma-4-31b-it-nvfp4",
    "vllm:nemotron-3-nano-30b-a3b-nvfp4",
    "vllm:exaone-4.0-32b-awq",
    "ollama:exaone3.5:7.8b",
    "ollama:llama-3.3-70b-instruct-q4-k-m",
]


def safe_label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")


def run_capture(command: list[str], *, timeout: int) -> tuple[int, float, str]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
        return completed.returncode, time.perf_counter() - started, completed.stdout + "\n" + completed.stderr
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\n" + (exc.stderr or "")
        return 124, time.perf_counter() - started, output


def stop_eval_servers() -> None:
    subprocess.run(["tmux", "kill-session", "-t", "sglang-local"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["tmux", "kill-session", "-t", "vllm-gemma4"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def process_snapshot() -> dict[str, str]:
    checks = {
        "tmux": ["bash", "-lc", "tmux ls 2>/dev/null || true"],
        "memory": ["bash", "-lc", "free -h | sed -n '1,3p'"],
        "sglang_endpoint": ["bash", "-lc", "curl -fsS http://127.0.0.1:30000/v1/models >/dev/null 2>&1 && echo up || echo down"],
        "vllm_endpoint": ["bash", "-lc", "curl -fsS http://127.0.0.1:30001/v1/models >/dev/null 2>&1 && echo up || echo down"],
        "llm_processes": [
            "bash",
            "-lc",
            "pgrep -af 'eval_large_model_rag|sglang serve|run-sglang-local|vllm.entrypoints|ollama serve' | sed -n '1,80p' || true",
        ],
    }
    snapshot: dict[str, str] = {}
    for name, command in checks.items():
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        snapshot[name] = completed.stdout.strip()
    return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch runner for answer-generation model evaluation.")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--cases", default="eval/policy_xlsx_qa.jsonl")
    parser.add_argument("--index-mode", default="v2_only", choices=["default", "v2_only", "v1_v2_combined"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--label-prefix", default=f"policy_xlsx_answer_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--summary-out", type=Path, default=ROOT / "reports" / "large_model_rag_eval" / "answer_model_batch_summary.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    summary = []
    for model in models:
        label = f"{args.label_prefix}_{safe_label(model)}"
        command = [
            sys.executable,
            "scripts/eval_large_model_rag.py",
            "--cases",
            args.cases,
            "--models",
            model,
            "--index-mode",
            args.index_mode,
            "--label",
            label,
            "--stop-llm-after",
        ]
        if args.limit:
            command += ["--limit", str(args.limit)]
        print(f"MODEL_START {model} label={label}", flush=True)
        exit_code, elapsed_s, output = run_capture(command, timeout=args.timeout)
        print(output[-6000:], flush=True)
        stop_eval_servers()
        time.sleep(3)
        snapshot = process_snapshot()
        row = {
            "model": model,
            "label": label,
            "exit": exit_code,
            "elapsed_s": round(elapsed_s, 1),
            "process_snapshot": snapshot,
        }
        summary.append(row)
        args.summary_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"MODEL_DONE {model} exit={exit_code} elapsed_s={elapsed_s:.1f}", flush=True)
        print(json.dumps(snapshot, ensure_ascii=False, indent=2), flush=True)
    print(f"summary_out: {args.summary_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
