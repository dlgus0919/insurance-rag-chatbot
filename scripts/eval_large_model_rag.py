#!/usr/bin/env python3
"""Evaluate large local LLMs on source-grounded insurance RAG QA cases."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.llm.factory import split_model_selection
from src.llm.ollama_client import OllamaClient
from src.llm.openai_compatible_client import OpenAICompatibleClient
from src.rag.pipeline import RagPipeline
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.index_mode import INDEX_MODES, resolve_index_paths
from src.retrieval.vector_store import VectorStore

DEFAULT_CASE_PATH = ROOT / "eval" / "large_model_rag_qa.jsonl"
DEFAULT_REPORT_DIR = ROOT / "reports" / "large_model_rag_eval"
DEFAULT_MODELS = ",".join(
    model
    for model in (config.SGLANG_CANDIDATE_MODELS or [config.SGLANG_DEFAULT_MODEL])
    if model not in config.SGLANG_DISABLED_MODELS
) or config.SGLANG_DEFAULT_MODEL
PAD_RE = re.compile(r"(?:<pad>\s*){3,}")
SOURCE_RE = re.compile(r"\[출처:")
HANGUL_RE = re.compile(r"[가-힣]")


@dataclass
class CaseResult:
    model: str
    index_mode: str
    case_id: str
    category: str
    question: str
    passed: bool
    checks: dict[str, bool]
    failures: list[str]
    answer: str
    top_sources: list[dict[str, Any]]
    timing: dict[str, float]
    error: str | None = None


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _page_hit(hit, pages: list[int]) -> bool:
    start = hit.metadata.get("page_start")
    end = hit.metadata.get("page_end", start)
    if start is None or end is None:
        return False
    return any(start <= page <= end for page in pages)


def _expected_source_recall(hits, expected_sources: list[dict[str, Any]]) -> bool:
    if not expected_sources:
        return True
    for expected in expected_sources:
        doc = expected.get("doc_short")
        pages = expected.get("pages", [])
        if not any(hit.metadata.get("doc_short") == doc and _page_hit(hit, pages) for hit in hits):
            return False
    return True


def _top_sources(chunks) -> list[dict[str, Any]]:
    rows = []
    for chunk in chunks[:5]:
        metadata = chunk.metadata
        rows.append(
            {
                "doc_short": metadata.get("doc_short"),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "preview": chunk.text[:160].replace("\n", " "),
            }
        )
    return rows


HYPHEN_TRANSLATION = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)


def _normalize_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).translate(HYPHEN_TRANSLATION)
    normalized = re.sub(
        r"(\d[\d,]*)\s*만\s*원?",
        lambda m: f"{int(m.group(1).replace(',', '')) * 10000}원",
        normalized,
    )
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)
    normalized = re.sub(r"(\d)\s+%", r"\1%", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _contains_term(normalized_answer: str, term: str) -> bool:
    normalized_term = _normalize_for_match(term)
    if normalized_term in normalized_answer:
        return True
    if not HANGUL_RE.search(normalized_term):
        return False
    compact_answer = _compact_korean_for_match(normalized_answer)
    compact_term = _compact_korean_for_match(normalized_term)
    return bool(compact_term) and compact_term in compact_answer


def _compact_korean_for_match(text: str) -> str:
    compact = text.replace(" ", "")
    return re.sub(r"(?<=[가-힣])(?:을|를|은|는)(?=[가-힣])", "", compact)


def _contains_all(answer: str, terms: list[str]) -> bool:
    normalized = _normalize_for_match(answer)
    return all(_contains_term(normalized, term) for term in terms)


def _contains_any(answer: str, terms: list[str]) -> bool:
    normalized = _normalize_for_match(answer)
    return any(_contains_term(normalized, term) for term in terms)


def _contains_no_any(answer: str, terms: list[str]) -> bool:
    normalized = _normalize_for_match(answer)
    return not any(_contains_term(normalized, term) for term in terms)


def _regex_all(answer: str, patterns: list[str]) -> bool:
    normalized = _normalize_for_match(answer)
    return all(re.search(pattern, normalized, flags=re.IGNORECASE | re.MULTILINE) for pattern in patterns)


def _line_contains_doc_and_term(answer: str, doc: str, term: str) -> bool:
    normalized_doc = _normalize_for_match(doc)
    normalized_term = _normalize_for_match(term)
    normalized_lines = [_normalize_for_match(line) for line in answer.splitlines()]
    normalized_answer = _normalize_for_match(answer)
    return any(normalized_doc in line and normalized_term in line for line in normalized_lines) or (
        normalized_doc in normalized_answer and normalized_term in normalized_answer
    )


def _by_doc_ok(answer: str, expected_by_doc: dict[str, list[str]]) -> bool:
    for doc, terms in expected_by_doc.items():
        for term in terms:
            if not _line_contains_doc_and_term(answer, doc, term):
                return False
    return True


def _forbidden_by_doc_ok(answer: str, forbidden_by_doc: dict[str, list[str]]) -> bool:
    for line in answer.splitlines():
        for doc, terms in forbidden_by_doc.items():
            if doc in line and any(term in line for term in terms):
                return False
    return True


def _min_docs_ok(answer: str, docs: list[str], minimum: int) -> bool:
    if minimum <= 0:
        return True
    return sum(1 for doc in docs if doc in answer) >= minimum


def _min_keyword_hits_ok(answer: str, spec: dict[str, Any] | None) -> bool:
    if not spec:
        return True
    keywords = spec.get("keywords", [])
    minimum = int(spec.get("min", len(keywords)))
    normalized = _normalize_for_match(answer)
    return sum(1 for keyword in keywords if _normalize_for_match(keyword) in normalized) >= minimum


def _required_groups_ok(answer: str, groups: list[list[str]]) -> bool:
    """Return whether every group has at least one matching expression."""

    if not groups:
        return True
    normalized = _normalize_for_match(answer)
    for group in groups:
        if not any(_contains_term(normalized, term) for term in group):
            return False
    return True


def _output_health_ok(answer: str) -> bool:
    stripped = answer.strip()
    if len(stripped) < 8:
        return False
    if PAD_RE.search(stripped):
        return False
    substantive = re.sub(r"\[출처:[^\]]+\]", "", stripped).strip()
    if len(substantive) < 8:
        return False
    tokens = stripped.split()
    if len(tokens) >= 12:
        most_common = max(tokens.count(token) for token in set(tokens))
        if most_common / len(tokens) > 0.65:
            return False
    return True


def evaluate_answer(case: dict[str, Any], answer: str, hits) -> tuple[dict[str, bool], list[str]]:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    expected_sources = case.get("expected_sources", [])
    checks["retrieval_expected_sources"] = case.get("allow_retrieval_miss", False) or _expected_source_recall(hits, expected_sources)
    checks["required_terms"] = _contains_all(answer, case.get("required_terms", []))
    checks["required_clause_terms"] = _contains_all(answer, case.get("required_clause_terms", []))
    checks["required_numbers"] = _contains_all(answer, case.get("required_numbers", []))
    checks["required_any"] = True if not case.get("required_any") else _contains_any(answer, case["required_any"])
    checks["required_groups"] = _required_groups_ok(answer, case.get("required_groups", []))
    checks["forbidden_terms"] = _contains_no_any(answer, case.get("forbidden_terms", []))
    checks["forbidden_any"] = True if not case.get("forbidden_any") else _contains_no_any(answer, case["forbidden_any"])
    checks["required_regex"] = _regex_all(answer, case.get("required_regex", []))
    checks["expected_by_doc"] = _by_doc_ok(answer, case.get("expected_by_doc", {}))
    checks["forbidden_by_doc"] = _forbidden_by_doc_ok(answer, case.get("forbidden_by_doc", {}))
    checks["min_docs_in_answer"] = _min_docs_ok(answer, case.get("doc_sources", []), int(case.get("min_docs_in_answer", 0)))
    checks["min_keyword_hits"] = _min_keyword_hits_ok(answer, case.get("min_keyword_hits"))
    checks["source_citation"] = bool(SOURCE_RE.search(answer))
    checks["no_evidence_warning"] = "[근거 검증 경고]" not in answer
    checks["output_health"] = _output_health_ok(answer)

    for name, ok in checks.items():
        if not ok:
            failures.append(name)
    return checks, failures


def parse_model_specs(raw: str) -> list[ModelSpec]:
    specs: list[ModelSpec] = []
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        provider, model = split_model_selection(text, default_provider="sglang")
        specs.append(ModelSpec(provider=provider, model=model))
    return specs


def switch_model(spec: ModelSpec, args) -> None:
    if spec.provider == "sglang":
        command = args.switch_command
        timeout = args.switch_timeout
    elif spec.provider == "vllm":
        command = args.vllm_switch_command
        timeout = args.vllm_switch_timeout
    elif spec.provider == "ollama":
        print(f"[model] {spec.id} uses running Ollama runtime; no switch command")
        return
    else:
        raise RuntimeError(f"unsupported local provider for evaluation: {spec.provider}")
    started = time.perf_counter()
    completed = subprocess.run([command, spec.model], text=True, capture_output=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        tail = (completed.stdout + "\n" + completed.stderr)[-4000:]
        raise RuntimeError(f"switch failed for {spec.id} (exit={completed.returncode})\n{tail}")
    elapsed = time.perf_counter() - started
    print(f"[model] {spec.id} active after {elapsed:.1f}s")


def stop_model_server(spec: ModelSpec) -> None:
    if spec.provider == "sglang":
        subprocess.run(["tmux", "kill-session", "-t", "sglang-local"], check=False)
    elif spec.provider == "vllm":
        subprocess.run(["tmux", "kill-session", "-t", "vllm-gemma4"], check=False)


def make_pipeline(spec: ModelSpec, args) -> RagPipeline:
    if spec.provider == "sglang":
        llm = OpenAICompatibleClient(
            model=spec.model,
            base_url=args.base_url,
            api_key=os.getenv("SGLANG_API_KEY", "EMPTY"),
            max_tokens=args.max_tokens,
            provider="sglang",
        )
        served_models = llm.list_models()
        if spec.model not in served_models:
            raise RuntimeError(
                f"SGLang endpoint is reachable but model {spec.model!r} is not served at {args.base_url}. "
                f"served={served_models}"
            )
    elif spec.provider == "vllm":
        llm = OpenAICompatibleClient(
            model=spec.model,
            base_url=args.vllm_base_url,
            api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
            max_tokens=args.max_tokens,
            provider="vllm",
        )
        served_models = llm.list_models()
        if spec.model not in served_models:
            raise RuntimeError(
                f"vLLM endpoint is reachable but model {spec.model!r} is not served at {args.vllm_base_url}. "
                f"served={served_models}"
            )
    elif spec.provider == "ollama":
        llm = OllamaClient(config.OLLAMA_HOST, spec.model)
    else:
        raise RuntimeError(f"unsupported local provider for evaluation: {spec.provider}")
    if args.embedder_device == "cpu":
        # Large SGLang servers reserve most GPU memory. Keep retrieval embedding on CPU for evaluation.
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    embedder = Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
    bm25_path, chroma_dir = resolve_index_paths(args.index_mode)
    vector_store = VectorStore(chroma_dir)
    bm25 = BM25Index.load(bm25_path)
    return RagPipeline(
        embedder=embedder,
        vector_store=vector_store,
        bm25=bm25,
        llm=llm,
        top_k_dense=config.TOP_K_DENSE,
        top_k_bm25=config.TOP_K_BM25,
        top_k_final=config.TOP_K_FINAL,
        rrf_k=config.RRF_K,
    )


def evaluate_model(spec: ModelSpec, cases: list[dict[str, Any]], args) -> list[CaseResult]:
    results: list[CaseResult] = []
    try:
        if not args.no_switch:
            switch_model(spec, args)
        pipeline = make_pipeline(spec, args)
        for index, case in enumerate(cases, start=1):
            started = time.perf_counter()
            try:
                answer = pipeline.answer(
                    case["question"],
                    temperature=args.temperature,
                    top_k=args.top_k,
                    doc_filter=case.get("doc_sources"),
                    return_debug=False,
                )
                checks, failures = evaluate_answer(case, answer.answer, answer.chunks)
                elapsed = time.perf_counter() - started
                passed = not failures
                result = CaseResult(
                    model=spec.id,
                    index_mode=args.index_mode,
                    case_id=case["id"],
                    category=case.get("category", ""),
                    question=case["question"],
                    passed=passed,
                    checks=checks,
                    failures=failures,
                    answer=answer.answer,
                    top_sources=_top_sources(answer.chunks),
                    timing={**answer.timing, "elapsed_s": elapsed},
                )
            except Exception as exc:
                result = CaseResult(
                    model=spec.id,
                    index_mode=args.index_mode,
                    case_id=case["id"],
                    category=case.get("category", ""),
                    question=case["question"],
                    passed=False,
                    checks={},
                    failures=["exception"],
                    answer="",
                    top_sources=[],
                    timing={"elapsed_s": time.perf_counter() - started},
                    error=str(exc),
                )
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"[{spec.id} {index:02d}/{len(cases)}] {status} {result.case_id} failures={','.join(result.failures) or '-'}")
    finally:
        if args.stop_llm_after and not args.no_switch:
            stop_model_server(spec)
    return results


def result_to_dict(result: CaseResult) -> dict[str, Any]:
    return {
        "model": result.model,
        "index_mode": result.index_mode,
        "case_id": result.case_id,
        "category": result.category,
        "question": result.question,
        "passed": result.passed,
        "checks": result.checks,
        "failures": result.failures,
        "answer": result.answer,
        "top_sources": result.top_sources,
        "timing": result.timing,
        "error": result.error,
    }


def write_reports(results: list[CaseResult], report_dir: Path, label: str) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = report_dir / f"large_model_rag_eval_{label}.jsonl"
    md_path = report_dir / f"large_model_rag_eval_{label}.md"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result_to_dict(result), ensure_ascii=False) + "\n")

    by_model: dict[str, list[CaseResult]] = {}
    for result in results:
        by_model.setdefault(result.model, []).append(result)
    index_modes = sorted({result.index_mode for result in results})
    lines = ["# Large Model RAG Evaluation", "", f"Generated: {label}", f"Index mode: {', '.join(index_modes) or '-'}", ""]
    for model, model_results in by_model.items():
        passed = sum(1 for result in model_results if result.passed)
        total = len(model_results)
        lines.extend([f"## {model}", "", f"- pass: {passed}/{total}", ""])
        for result in model_results:
            status = "PASS" if result.passed else "FAIL"
            failures = ", ".join(result.failures) if result.failures else "-"
            lines.append(f"- {status} `{result.case_id}` ({result.category}) failures={failures}")
            if result.error:
                lines.append(f"  - error: {result.error[:300]}")
            if not result.passed and result.answer:
                preview = result.answer.replace("\n", " ")[:260]
                lines.append(f"  - answer: {preview}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return jsonl_path, md_path


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Evaluate large local LLM models on insurance RAG QA cases.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASE_PATH)
    parser.add_argument("--models", default=os.getenv("LARGE_RAG_EVAL_MODELS", DEFAULT_MODELS))
    parser.add_argument(
        "--index-mode",
        choices=INDEX_MODES,
        default=os.getenv("LARGE_RAG_EVAL_INDEX_MODE", "v2_only"),
        help="Retrieval index mode. Use v2_only for manual-corrected OCR evaluation.",
    )
    parser.add_argument("--base-url", default=os.getenv("SGLANG_BASE_URL", "http://127.0.0.1:30000/v1"))
    parser.add_argument("--vllm-base-url", default=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:30001/v1"))
    parser.add_argument("--switch-command", default=os.getenv("SGLANG_SWITCH_SCRIPT", "/srv/ai-ops/bin/switch-sglang-model"))
    parser.add_argument("--switch-timeout", type=int, default=int(os.getenv("SGLANG_SWITCH_TIMEOUT", "900")))
    parser.add_argument("--vllm-switch-command", default=os.getenv("VLLM_SWITCH_SCRIPT", "/srv/ai-ops/bin/switch-vllm-model"))
    parser.add_argument("--vllm-switch-timeout", type=int, default=int(os.getenv("VLLM_SWITCH_TIMEOUT", "1200")))
    parser.add_argument("--no-switch", action="store_true", help="Do not switch SGLang model before each model run.")
    parser.add_argument("--stop-llm-after", action="store_true", help="Stop the SGLang/vLLM tmux session after each model run.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument(
        "--embedder-device",
        choices=["cpu", "auto"],
        default=os.getenv("LARGE_RAG_EVAL_EMBEDDER_DEVICE", "cpu"),
        help="Use CPU embedding by default to avoid GPU OOM while SGLang is loaded.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit number of cases for quick checks.")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--label", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args(argv)
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("No evaluation cases loaded.")
    models = parse_model_specs(args.models)
    all_results: list[CaseResult] = []
    for model in models:
        all_results.extend(evaluate_model(model, cases, args))
    jsonl_path, md_path = write_reports(all_results, args.report_dir, args.label)
    total = len(all_results)
    passed = sum(1 for result in all_results if result.passed)
    print(f"summary: {passed}/{total} passed")
    print(f"jsonl: {jsonl_path}")
    print(f"md: {md_path}")
    if passed < total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
