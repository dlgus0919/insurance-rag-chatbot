#!/usr/bin/env python3
"""Evaluate automatic RAG Top-K and temperature policies on policy QA cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_large_model_rag import (
    DEFAULT_MODELS,
    ModelSpec,
    evaluate_answer,
    load_cases,
    make_pipeline,
    parse_model_specs,
    stop_model_server,
    switch_model,
    _top_sources,
)
from src import config
from src.rag.auto_params import (
    TOPK_STRATEGY_RERANKER_THRESHOLD,
    TOPK_STRATEGY_RULE,
    resolve_auto_rag_params,
)
from src.rag.search_intent import classify_search_intent
from src.retrieval.index_mode import INDEX_MODES

DEFAULT_CASE_PATH = ROOT / "eval" / "policy_xlsx_qa.jsonl"
DEFAULT_REPORT_DIR = ROOT / "reports" / "auto_rag_params_eval"


@dataclass
class EvalRun:
    label: str
    strategy: str
    top_k_strategy: str
    temperature: float | None
    fixed_top_k: int | None = None


@dataclass
class AutoParamEvalResult:
    model: str
    index_mode: str
    strategy: str
    top_k_strategy: str
    case_id: str
    category: str
    profile: str
    question: str
    passed: bool
    checks: dict[str, bool]
    failures: list[str]
    answer: str
    top_sources: list[dict[str, Any]]
    run_top_k: int | None
    run_temperature: float | None
    auto_params: dict[str, Any] | None
    auto_cutoff: dict[str, Any] | None
    reranker_scores: list[dict[str, Any]]
    quality: dict[str, Any]
    timing: dict[str, float]
    error: str | None = None


def _case_doc_filter(case: dict[str, Any]) -> list[str] | None:
    docs = case.get("doc_sources")
    if not isinstance(docs, list):
        return None
    values = [str(item).strip() for item in docs if str(item).strip()]
    return values or None


def _profile_for_case(case: dict[str, Any]) -> str:
    return classify_search_intent(case["question"], doc_filter=_case_doc_filter(case)).intent


def _make_runs(args) -> list[EvalRun]:
    stages = [item.strip() for item in args.stage.split(",") if item.strip()]
    if "all" in stages:
        stages = ["baseline", "rule", "threshold", "temperature_grid"]
    runs: list[EvalRun] = []
    if "baseline" in stages:
        runs.append(
            EvalRun(
                label="baseline",
                strategy="baseline_fixed",
                top_k_strategy=TOPK_STRATEGY_RULE,
                temperature=args.baseline_temperature,
                fixed_top_k=args.baseline_top_k,
            )
        )
    if "rule" in stages:
        runs.append(
            EvalRun(
                label="rule",
                strategy="rule_auto",
                top_k_strategy=TOPK_STRATEGY_RULE,
                temperature=None,
            )
        )
    if "threshold" in stages:
        runs.append(
            EvalRun(
                label="threshold",
                strategy="threshold_auto",
                top_k_strategy=TOPK_STRATEGY_RERANKER_THRESHOLD,
                temperature=None,
            )
        )
    if "temperature_grid" in stages:
        for temp in _parse_float_list(args.temperature_grid):
            runs.append(
                EvalRun(
                    label=f"temp_{temp:g}",
                    strategy=f"temperature_grid_{temp:g}",
                    top_k_strategy=TOPK_STRATEGY_RULE,
                    temperature=temp,
                )
            )
    if not runs:
        raise SystemExit(f"No valid stage selected: {args.stage}")
    return runs


def _parse_float_list(raw: str) -> list[float]:
    values: list[float] = []
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        values.append(float(text))
    return values or [0.0]


def _stage_hit_payload(hit) -> dict[str, Any]:
    return {
        "chunk_id": getattr(hit, "chunk_id", ""),
        "doc_short": getattr(hit, "doc_short", ""),
        "score": getattr(hit, "score", None),
        "rank": getattr(hit, "rank", None),
        "page_start": getattr(hit, "page_start", None),
        "page_end": getattr(hit, "page_end", None),
        "text_preview": getattr(hit, "text_preview", ""),
    }


def _quality_metrics(answer: str, profile: str) -> dict[str, Any]:
    text = (answer or "").strip()
    length = len(text)
    profile_max = {
        "exact_code_lookup": 1300,
        "exact_code_compound_lookup": 1500,
        "procedure_code_lookup": 1300,
        "clause_or_appendix_lookup": 1600,
        "clause_detail_lookup": 1900,
        "coverage_judgment": 2000,
        "cross_doc_compare": 2400,
        "ambiguous_medical_term": 2000,
        "general_explanation": 2200,
    }.get(profile, 2200)
    min_length = 60 if profile.startswith("exact_code") else 90
    has_structure = any(line.strip().startswith(("-", "|", "1.", "2.", "3.")) for line in text.splitlines())
    forbidden_tone = any(
        marker in text
        for marker in (
            "안녕하세요",
            "친애하는",
            "도움이 되었기를",
            "저는 AI",
            "제가 보기에는",
        )
    )
    metrics = {
        "answer_chars": length,
        "too_short": length < min_length,
        "too_verbose": length > profile_max,
        "has_structure": has_structure,
        "tone_ok": not forbidden_tone,
    }
    score = 1.0
    if metrics["too_short"]:
        score -= 0.25
    if metrics["too_verbose"]:
        score -= 0.15
    if not metrics["tone_ok"]:
        score -= 0.20
    if profile in {"coverage_judgment", "cross_doc_compare", "clause_detail_lookup"} and not has_structure:
        score -= 0.10
    metrics["score"] = round(max(0.0, score), 3)
    return metrics


def _resolve_run_params(case: dict[str, Any], run: EvalRun, args) -> tuple[int, float, Any | None]:
    doc_filter = _case_doc_filter(case)
    filters = {"doc_filter": doc_filter} if doc_filter else {}
    if run.strategy == "baseline_fixed":
        return int(run.fixed_top_k or args.baseline_top_k), float(run.temperature or args.baseline_temperature), None

    decision = resolve_auto_rag_params(
        question=case["question"],
        mode="general",
        filters=filters,
        requested_top_k=args.baseline_top_k,
        requested_temperature=args.baseline_temperature,
        auto_params=True,
        config_mode="apply",
        max_temperature=args.max_auto_temperature,
        top_k_strategy=run.top_k_strategy,
        temperature_policy_path=args.temperature_policy,
    )
    temperature = float(run.temperature) if run.temperature is not None else decision.effective_temperature
    top_k = decision.retrieval_top_k or decision.effective_top_k
    return top_k, temperature, decision


def evaluate_model(spec: ModelSpec, cases: list[dict[str, Any]], runs: list[EvalRun], args) -> list[AutoParamEvalResult]:
    results: list[AutoParamEvalResult] = []
    try:
        if not args.no_switch:
            switch_model(spec, args)
        pipeline = make_pipeline(spec, args)
        total = len(cases) * len(runs)
        count = 0
        for case in cases:
            profile = _profile_for_case(case)
            for run in runs:
                count += 1
                started = time.perf_counter()
                try:
                    top_k, temperature, decision = _resolve_run_params(case, run, args)
                    answer = pipeline.answer(
                        case["question"],
                        temperature=temperature,
                        top_k=top_k,
                        doc_filter=_case_doc_filter(case),
                        return_debug=True,
                        auto_params=decision,
                    )
                    checks, failures = evaluate_answer(case, answer.answer, answer.chunks)
                    quality = _quality_metrics(answer.answer, profile)
                    if quality["too_short"]:
                        failures.append("quality_too_short")
                    if not quality["tone_ok"]:
                        failures.append("quality_tone")
                    elapsed = time.perf_counter() - started
                    result = AutoParamEvalResult(
                        model=spec.id,
                        index_mode=args.index_mode,
                        strategy=run.strategy,
                        top_k_strategy=run.top_k_strategy,
                        case_id=case["id"],
                        category=case.get("category", ""),
                        profile=profile,
                        question=case["question"],
                        passed=not failures,
                        checks=checks,
                        failures=failures,
                        answer=answer.answer,
                        top_sources=_top_sources(answer.chunks),
                        run_top_k=top_k,
                        run_temperature=temperature,
                        auto_params=decision.to_payload() if decision else None,
                        auto_cutoff=(
                            answer.debug.auto_cutoff.to_payload()
                            if answer.debug is not None and hasattr(answer.debug.auto_cutoff, "to_payload")
                            else None
                        ),
                        reranker_scores=[
                            _stage_hit_payload(hit)
                            for hit in list(getattr(answer.debug, "reranker_scores", []) or [])
                        ] if answer.debug is not None else [],
                        quality=quality,
                        timing={**answer.timing, "elapsed_s": elapsed},
                    )
                except Exception as exc:
                    result = AutoParamEvalResult(
                        model=spec.id,
                        index_mode=args.index_mode,
                        strategy=run.strategy,
                        top_k_strategy=run.top_k_strategy,
                        case_id=case["id"],
                        category=case.get("category", ""),
                        profile=profile,
                        question=case["question"],
                        passed=False,
                        checks={},
                        failures=["exception"],
                        answer="",
                        top_sources=[],
                        run_top_k=None,
                        run_temperature=None,
                        auto_params=None,
                        auto_cutoff=None,
                        reranker_scores=[],
                        quality={"score": 0.0},
                        timing={"elapsed_s": time.perf_counter() - started},
                        error=str(exc),
                    )
                results.append(result)
                status = "PASS" if result.passed else "FAIL"
                print(
                    f"[{spec.id} {count:03d}/{total:03d}] "
                    f"{status} {run.strategy} {result.case_id} failures={','.join(result.failures) or '-'}"
                )
    finally:
        if args.stop_llm_after and not args.no_switch:
            stop_model_server(spec)
    return results


def _result_to_dict(result: AutoParamEvalResult) -> dict[str, Any]:
    return {
        "model": result.model,
        "index_mode": result.index_mode,
        "strategy": result.strategy,
        "top_k_strategy": result.top_k_strategy,
        "case_id": result.case_id,
        "category": result.category,
        "profile": result.profile,
        "question": result.question,
        "passed": result.passed,
        "checks": result.checks,
        "failures": result.failures,
        "answer": result.answer,
        "top_sources": result.top_sources,
        "run_top_k": result.run_top_k,
        "run_temperature": result.run_temperature,
        "auto_params": result.auto_params,
        "auto_cutoff": result.auto_cutoff,
        "reranker_scores": result.reranker_scores,
        "quality": result.quality,
        "timing": result.timing,
        "error": result.error,
    }


def _aggregate(results: list[AutoParamEvalResult]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for result in results:
        item = summary.setdefault(
            result.strategy,
            {
                "total": 0,
                "passed": 0,
                "quality_score_sum": 0.0,
                "avg_answer_chars_sum": 0,
                "profiles": {},
            },
        )
        item["total"] += 1
        item["passed"] += int(result.passed)
        item["quality_score_sum"] += float(result.quality.get("score", 0.0))
        item["avg_answer_chars_sum"] += int(result.quality.get("answer_chars", 0))
        profile = item["profiles"].setdefault(result.profile, {"total": 0, "passed": 0})
        profile["total"] += 1
        profile["passed"] += int(result.passed)
    for item in summary.values():
        total = max(1, item["total"])
        item["pass_rate"] = round(item["passed"] / total, 4)
        item["avg_quality_score"] = round(item["quality_score_sum"] / total, 4)
        item["avg_answer_chars"] = round(item["avg_answer_chars_sum"] / total, 1)
        del item["quality_score_sum"]
        del item["avg_answer_chars_sum"]
        for profile in item["profiles"].values():
            profile["pass_rate"] = round(profile["passed"] / max(1, profile["total"]), 4)
    return summary


def write_reports(results: list[AutoParamEvalResult], report_dir: Path, label: str) -> tuple[Path, Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = report_dir / f"auto_rag_params_eval_{label}.jsonl"
    md_path = report_dir / f"auto_rag_params_eval_{label}.md"
    summary_path = report_dir / f"auto_rag_params_eval_{label}.summary.json"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(_result_to_dict(result), ensure_ascii=False) + "\n")

    summary = _aggregate(results)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    ranked = sorted(
        summary.items(),
        key=lambda item: (item[1]["pass_rate"], item[1]["avg_quality_score"]),
        reverse=True,
    )
    lines = [
        "# Auto RAG Parameter Evaluation",
        "",
        f"Generated: {label}",
        f"Index mode: {', '.join(sorted({result.index_mode for result in results}))}",
        f"Model: {', '.join(sorted({result.model for result in results}))}",
        "",
        "## Strategy Summary",
        "",
        "| strategy | pass | pass rate | avg quality | avg chars |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for strategy, item in ranked:
        lines.append(
            f"| {strategy} | {item['passed']}/{item['total']} | "
            f"{item['pass_rate']:.2%} | {item['avg_quality_score']:.3f} | {item['avg_answer_chars']} |"
        )
    if ranked:
        lines.extend(["", f"Recommended by automated score: `{ranked[0][0]}`", ""])

    lines.extend(["## Failure Samples", ""])
    for result in results:
        if result.passed:
            continue
        failures = ", ".join(result.failures) or "-"
        answer_preview = result.answer.replace("\n", " ")[:260]
        lines.append(f"- `{result.strategy}` `{result.case_id}` ({result.profile}) failures={failures}")
        if result.error:
            lines.append(f"  - error: {result.error[:300]}")
        elif answer_preview:
            lines.append(f"  - answer: {answer_preview}")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return jsonl_path, md_path, summary_path


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Evaluate automatic RAG parameter policies.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASE_PATH)
    parser.add_argument("--models", default=os.getenv("AUTO_RAG_EVAL_MODELS", DEFAULT_MODELS))
    parser.add_argument(
        "--stage",
        default=os.getenv("AUTO_RAG_EVAL_STAGE", "baseline,rule,threshold"),
        help="Comma-separated stages: baseline, rule, threshold, temperature_grid, all.",
    )
    parser.add_argument("--temperature-grid", default=os.getenv("AUTO_RAG_TEMPERATURE_GRID", "0,0.1,0.2"))
    parser.add_argument("--baseline-top-k", type=int, default=10)
    parser.add_argument("--baseline-temperature", type=float, default=0.2)
    parser.add_argument("--max-auto-temperature", type=float, default=config.AUTO_RAG_MAX_TEMPERATURE)
    parser.add_argument("--temperature-policy", type=Path, default=config.AUTO_RAG_TEMPERATURE_POLICY_PATH)
    parser.add_argument(
        "--index-mode",
        choices=INDEX_MODES,
        default=os.getenv("AUTO_RAG_EVAL_INDEX_MODE", "v2_only"),
        help="Use v2_only so corrected OCR data is always included.",
    )
    parser.add_argument("--base-url", default=os.getenv("SGLANG_BASE_URL", "http://127.0.0.1:30000/v1"))
    parser.add_argument("--vllm-base-url", default=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:30001/v1"))
    parser.add_argument("--switch-command", default=os.getenv("SGLANG_SWITCH_SCRIPT", "/srv/ai-ops/bin/switch-sglang-model"))
    parser.add_argument("--switch-timeout", type=int, default=int(os.getenv("SGLANG_SWITCH_TIMEOUT", "900")))
    parser.add_argument("--vllm-switch-command", default=os.getenv("VLLM_SWITCH_SCRIPT", "/srv/ai-ops/bin/switch-vllm-model"))
    parser.add_argument("--vllm-switch-timeout", type=int, default=int(os.getenv("VLLM_SWITCH_TIMEOUT", "1200")))
    parser.add_argument("--no-switch", action="store_true")
    parser.add_argument("--stop-llm-after", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument(
        "--embedder-device",
        choices=["cpu", "auto"],
        default=os.getenv("AUTO_RAG_EVAL_EMBEDDER_DEVICE", "cpu"),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--label", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("No evaluation cases loaded.")
    runs = _make_runs(args)
    all_results: list[AutoParamEvalResult] = []
    for model in parse_model_specs(args.models):
        all_results.extend(evaluate_model(model, cases, runs, args))
    jsonl_path, md_path, summary_path = write_reports(all_results, args.report_dir, args.label)
    summary = _aggregate(all_results)
    best = sorted(
        summary.items(),
        key=lambda item: (item[1]["pass_rate"], item[1]["avg_quality_score"]),
        reverse=True,
    )[0]
    print(f"best_strategy: {best[0]} pass_rate={best[1]['pass_rate']:.2%} quality={best[1]['avg_quality_score']:.3f}")
    print(f"jsonl: {jsonl_path}")
    print(f"md: {md_path}")
    print(f"summary: {summary_path}")


if __name__ == "__main__":
    main()
