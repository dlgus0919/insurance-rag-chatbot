#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.factory import split_model_selection
from src.llm.openai_compatible_client import OpenAICompatibleClient
from src.ontology.llm_batch import LlmBatchConfig, maybe_start_llm_server, maybe_stop_llm_server
from src.ontology.llm_enrichment import (
    EnrichmentParseResult,
    build_enrichment_input,
    enrich_candidate_with_llm,
    is_unsafe_approval,
    summarize_enrichment_rows,
    template_enrichment,
    validate_enrichment_output,
)
from src.ontology.review_store import OntologyCandidate


DEFAULT_MODELS = "sglang:qwen3-next-80b-a3b-instruct-fp8,sglang:qwen3-30b-a3b-instruct-2507-fp8,sglang:gpt-oss-20b"
DEFAULT_REPORT_DIR = ROOT / "reports" / "ontology_llm_enrichment_eval"


def _utc_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
            return [item for item in payload["candidates"] if isinstance(item, dict)]
        if isinstance(payload, dict):
            return [payload]
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        value = json.loads(stripped)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def load_candidates(path: Path, *, limit: int | None = None) -> list[OntologyCandidate]:
    candidates = [OntologyCandidate.from_dict(row) for row in _read_json_or_jsonl(path)]
    if limit is not None:
        candidates = candidates[:limit]
    return candidates


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def expected_enrichment_spec(candidate: OntologyCandidate) -> dict[str, list[str]]:
    properties = candidate.properties if isinstance(candidate.properties, dict) else {}
    expected = properties.get("expected_enrichment") if isinstance(properties.get("expected_enrichment"), dict) else {}
    return {
        "expected_decisions": _string_list(expected.get("expected_decisions")),
        "forbidden_decisions": _string_list(expected.get("forbidden_decisions")),
        "required_reason_codes": _string_list(expected.get("required_reason_codes")),
    }


def evaluate_expected_enrichment(candidate: OntologyCandidate, payload: dict[str, Any]) -> dict[str, Any]:
    spec = expected_enrichment_spec(candidate)
    decision = str(payload.get("overall_decision") or "").strip()
    emitted_reason_codes: set[str] = set()
    for item in payload.get("alias_assessments", []):
        if isinstance(item, dict):
            emitted_reason_codes.update(_string_list(item.get("reason_codes")))

    has_expected = any(spec.values())
    expected_decisions_ok = not spec["expected_decisions"] or decision in set(spec["expected_decisions"])
    forbidden_decisions_ok = not spec["forbidden_decisions"] or decision not in set(spec["forbidden_decisions"])
    required_reason_codes_ok = not spec["required_reason_codes"] or set(spec["required_reason_codes"]).issubset(emitted_reason_codes)
    return {
        "has_expected_enrichment": has_expected,
        "expected_decisions": spec["expected_decisions"],
        "forbidden_decisions": spec["forbidden_decisions"],
        "required_reason_codes": spec["required_reason_codes"],
        "emitted_reason_codes": sorted(emitted_reason_codes),
        "expected_decisions_ok": expected_decisions_ok,
        "forbidden_decisions_ok": forbidden_decisions_ok,
        "required_reason_codes_ok": required_reason_codes_ok,
        "expected_checks_ok": expected_decisions_ok and forbidden_decisions_ok and required_reason_codes_ok,
    }


def parse_model_specs(raw: str) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        provider, model = split_model_selection(text, default_provider="sglang")
        if provider == "ollama":
            raise SystemExit("Ontology enrichment evaluation excludes Ollama models.")
        if provider not in {"sglang", "vllm"}:
            raise SystemExit(f"Unsupported ontology enrichment provider: {provider}")
        specs.append((provider, model))
    return specs


def _client_for(provider: str, model: str, base_url: str, max_tokens: int) -> OpenAICompatibleClient:
    api_key = os.getenv("VLLM_API_KEY", "EMPTY") if provider == "vllm" else os.getenv("SGLANG_API_KEY", "EMPTY")
    return OpenAICompatibleClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
        max_tokens=max_tokens,
        provider=provider,
    )


def _run_one_model(
    *,
    provider: str,
    model: str,
    candidates: list[OntologyCandidate],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    llm_config = LlmBatchConfig(
        llm=provider,
        model=model,
        start_llm=args.start_llm,
        stop_llm_after=args.stop_llm_after,
        llm_base_url=args.base_url if provider == "sglang" else args.vllm_base_url,
        timeout=args.llm_timeout,
    )
    selection = maybe_start_llm_server(llm_config, dry_run=args.dry_run)
    base_url = selection.base_url if selection else (args.vllm_base_url if provider == "vllm" else args.base_url)
    client = None if args.dry_run else _client_for(provider, model, base_url, args.max_tokens)
    rows: list[dict[str, Any]] = []
    try:
        for index, candidate in enumerate(candidates, start=1):
            if args.dry_run:
                payload = template_enrichment(candidate, all_candidates=candidates)
                normalized, errors = validate_enrichment_output(payload)
                parse_result = EnrichmentParseResult(
                    payload=normalized,
                    validation_errors=errors,
                    raw_text=json.dumps(payload, ensure_ascii=False),
                    json_valid=True,
                    schema_valid=not errors,
                )
            else:
                if client is None:
                    raise RuntimeError("LLM client was not initialized.")
                parse_result = enrich_candidate_with_llm(
                    candidate,
                    client,
                    all_candidates=candidates,
                    temperature=args.temperature,
                )
            enrichment_input = build_enrichment_input(candidate, all_candidates=candidates)
            row = {
                "model": f"{provider}:{model}",
                "provider": provider,
                "candidate_index": index,
                "candidate_id": candidate.candidate_id,
                "concept_id": candidate.concept_id,
                "canonical_name": candidate.canonical_name,
                "candidate_status": candidate.status,
                "candidate_aliases": candidate.candidate_aliases,
                "known_conflict_count": len(enrichment_input.get("known_conflicts", [])),
                "quality_warning_codes": [item.get("code") for item in enrichment_input.get("quality_warnings", [])],
                "overall_decision": parse_result.payload.get("overall_decision"),
                "risk_level": parse_result.payload.get("risk_level"),
                "json_valid": parse_result.json_valid,
                "schema_valid": parse_result.schema_valid,
                "validation_errors": parse_result.validation_errors,
                "raw_text_preview": parse_result.raw_text[:1200] if parse_result.validation_errors else "",
                "unsafe_approval": is_unsafe_approval(candidate, parse_result.payload),
                "enrichment": parse_result.payload,
            }
            row.update(evaluate_expected_enrichment(candidate, parse_result.payload))
            rows.append(row)
            status = "OK" if row["schema_valid"] else "SCHEMA_FAIL"
            print(f"[{provider}:{model} {index:03d}/{len(candidates):03d}] {status} {candidate.candidate_id}")
    finally:
        maybe_stop_llm_server(llm_config, selection, dry_run=args.dry_run)
    return rows


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def write_markdown(rows: list[dict[str, Any]], path: Path, *, dry_run: bool) -> None:
    summary = summarize_enrichment_rows(rows)
    lines = [
        "# Ontology LLM Enrichment Evaluation",
        "",
        f"- generated_at: {_utc_label()}",
        f"- dry_run: {str(dry_run).lower()}",
        f"- total_rows: {len(rows)}",
        "",
        "## Model Summary",
        "",
        "| model | total | decisions | json_validity | schema_validity | unsafe_approval | expected_pass | held_as_approve | rejected_as_approve | applied_as_reject |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, item in sorted(summary.items()):
        decisions = ", ".join(f"{key}:{value}" for key, value in sorted(item["decision_counts"].items()))
        lines.append(
            "| {model} | {total} | {decisions} | {json:.2%} | {schema:.2%} | {unsafe} | {expected_pass}/{expected_total} ({expected_rate:.2%}) | {held} | {rejected} | {applied} |".format(
                model=model,
                total=item["total"],
                decisions=decisions or "-",
                json=item["json_validity"],
                schema=item["schema_validity"],
                unsafe=item["unsafe_approval_count"],
                expected_pass=item["expected_pass"],
                expected_total=item["expected_total"],
                expected_rate=item["expected_pass_rate"],
                held=item["held_as_approve"],
                rejected=item["rejected_as_approve"],
                applied=item["applied_as_reject"],
            )
        )
    lines.extend(
        [
            "",
            "## Decision Matrix Seed",
            "",
            "이 표는 실제 LLM 비교 결과가 누적된 뒤 승인된 내부 decision matrix에 병합하기 위한 seed입니다.",
            "",
            "| model | ontology_role | delete_blocker | note |",
            "|---|---|---|---|",
        ]
    )
    for model, item in sorted(summary.items()):
        expected_gate_failed = item["expected_total"] > 0 and item["expected_pass_rate"] < 0.80
        if item["unsafe_approval_count"] > 0 or item["schema_validity"] < 0.98 or expected_gate_failed:
            role = "none"
            blocker = ""
            note = "unsafe approval, schema 안정성, 또는 expected edge-case 기준 미달"
        else:
            role = "reserved"
            blocker = "ontology_role=reserved"
            note = "shadow 평가 통과 후보. 실제 모델 비교 후 primary/fallback 결정 필요"
        lines.append(f"| {model} | {role} | {blocker or '-'} | {note} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate local LLMs for ontology candidate enrichment shadow tasks.")
    parser.add_argument("--input", type=Path, required=True, help="Candidate JSON or JSONL input.")
    parser.add_argument("--extra-input", action="append", type=Path, default=[], help="Additional candidate JSON/JSONL inputs, e.g. gold or synthetic edge cases.")
    parser.add_argument("--models", default=DEFAULT_MODELS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Use deterministic template enrichment instead of LLM calls.")
    parser.add_argument("--start-llm", action="store_true")
    parser.add_argument("--stop-llm-after", action="store_true")
    parser.add_argument("--base-url", default=os.getenv("SGLANG_BASE_URL", "http://127.0.0.1:30000/v1"))
    parser.add_argument("--vllm-base-url", default=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:30001/v1"))
    parser.add_argument("--llm-timeout", type=int, default=int(os.getenv("ONTOLOGY_LLM_TIMEOUT", "1800")))
    parser.add_argument("--max-tokens", type=int, default=int(os.getenv("ONTOLOGY_LLM_MAX_TOKENS", "1600")))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--label", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    candidates = load_candidates(args.input, limit=args.limit)
    for extra_input in args.extra_input:
        candidates.extend(load_candidates(extra_input))
    if not candidates:
        raise SystemExit("No ontology candidates loaded.")

    rows: list[dict[str, Any]] = []
    for provider, model in parse_model_specs(args.models):
        rows.extend(_run_one_model(provider=provider, model=model, candidates=candidates, args=args))

    label = args.label.strip() or _utc_label()
    jsonl_path = args.report_dir / f"{label}.jsonl"
    md_path = args.report_dir / f"{label}.md"
    write_jsonl(rows, jsonl_path)
    write_markdown(rows, md_path, dry_run=args.dry_run)
    print(json.dumps({"jsonl": str(jsonl_path), "markdown": str(md_path), "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
