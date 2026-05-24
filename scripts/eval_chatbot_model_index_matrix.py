#!/usr/bin/env python3
"""Evaluate chatbot RAG on Model x Index matrix combinations."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.llm.openai_compatible_client import OpenAICompatibleClient
from src.rag.pipeline import RagPipeline
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.vector_store import VectorStore
from src.retrieval.index_mode import resolve_index_paths

PAD_RE = re.compile(r"(?:<pad>\s*){3,}")
SOURCE_RE = re.compile(r"\[출처:")

MODEL_CONFIGS = {
    "gemma4_vllm": {
        "provider": "vllm",
        "model": "gemma-4-26b-a4b-nvfp4",
        "base_url": "http://127.0.0.1:30001/v1",
        "api_key": "EMPTY",
        "switch_command": "/srv/ai-ops/bin/switch-vllm-model",
        "switch_timeout": 1200,
    },
    "gpt_oss_sglang": {
        "provider": "sglang",
        "model": "gpt-oss-20b",
        "base_url": "http://127.0.0.1:30000/v1",
        "api_key": "EMPTY",
        "switch_command": "/srv/ai-ops/bin/switch-sglang-model",
        "switch_timeout": 900,
    }
}

MATRIX_COLUMNS = [
    "default__vllm_gemma4",
    "v2_only__vllm_gemma4",
    "v1_v2_combined__vllm_gemma4",
    "default__sglang_gpt_oss_20b",
    "v2_only__sglang_gpt_oss_20b",
    "v1_v2_combined__sglang_gpt_oss_20b",
]

MODEL_KEY_BY_SIGNATURE = {
    (cfg["provider"], cfg["model"]): key
    for key, cfg in MODEL_CONFIGS.items()
}
MODEL_REPORT_ALIAS = {
    "gemma4_vllm": "vllm_gemma4",
    "gpt_oss_sglang": "sglang_gpt_oss_20b",
}

CATEGORY_SCORE_WEIGHTS = {
    "negative_control": 4,
    "safety_legal_advice": 4,
    "safety_prompt_injection": 4,
    "cross_doc_source_specific_code": 3,
    "ocr_manual_disability_criteria": 3,
    "ocr_manual_disability_rate": 3,
    "ocr_manual_surgery_grade": 3,
    "single_doc_hira_code_table": 3,
    "single_doc_hira_multi_row_code_table": 3,
    "single_doc_policy_coverage": 3,
    "single_doc_policy_definition": 3,
    "ocr_v1_v2_mapping": 3,
    "ocr_casebook_consultation": 2,
    "ocr_casebook_multi_fact": 2,
    "smoke_system_fallback": 1,
}
DEFAULT_SCORE_WEIGHT = 2


@dataclass
class CaseResult:
    label: str
    case_id: str
    category: str
    question: str
    difficulty: str
    review_type: str
    index_mode: str
    matrix_id: str
    provider: str
    model: str
    eligible: bool
    passed: bool
    checks: dict[str, bool]
    failures: list[str]
    answer: str
    top_sources: list[dict[str, Any]]
    timing: dict[str, float]
    defect_type: str | None
    error: str | None = None


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _split_csv(value: str | None, default: list[str] | None = None) -> list[str]:
    """쉼표 구분 CLI 값을 공백 제거 및 중복 제거해 반환한다."""

    if value is None or not value.strip():
        return list(default or [])
    items: list[str] = []
    for item in value.split(","):
        item = item.strip()
        if item and item not in items:
            items.append(item)
    return items


def _matches_filter(value: str | None, selected: list[str]) -> bool:
    """`all` 또는 빈 선택지를 전체 허용으로 처리하는 필터 매칭."""

    if not selected or "all" in selected:
        return True
    return (value or "") in selected


def score_weight_for_category(category: str | None) -> int:
    """고위험 보험/안전/정형값 문항에 더 큰 점수를 부여한다."""

    return CATEGORY_SCORE_WEIGHTS.get(category or "", DEFAULT_SCORE_WEIGHT)


def weighted_score(results: list[CaseResult]) -> tuple[int, int, float]:
    """eligible row 기준 가중 통과 점수를 반환한다."""

    earned = 0
    total = 0
    for result in results:
        if not result.eligible:
            continue
        weight = score_weight_for_category(result.category)
        total += weight
        if result.passed and not result.error:
            earned += weight
    score = (earned / total * 100) if total else 0.0
    return earned, total, score


def matrix_id_for(index_mode: str, provider: str, model: str) -> str:
    """보고서/pivot에서 사용할 안정적인 matrix ID를 반환한다."""

    model_key = MODEL_KEY_BY_SIGNATURE.get((provider, model), f"{provider}_{model}".replace("-", "_"))
    return f"{index_mode}__{MODEL_REPORT_ALIAS.get(model_key, model_key)}"


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
        text = getattr(chunk, "text", getattr(chunk, "document", ""))
        rows.append(
            {
                "doc_short": metadata.get("doc_short"),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "preview": text[:160].replace("\n", " "),
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
    normalized = re.sub(r"[*_`]+", "", normalized)
    normalized = re.sub(r"(\d)\s+%", r"\1%", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _contains_all(answer: str, terms: list[str]) -> bool:
    normalized = _normalize_for_match(answer)
    return all(_normalize_for_match(term) in normalized for term in terms)


def _contains_any(answer: str, terms: list[str]) -> bool:
    normalized = _normalize_for_match(answer)
    return any(_normalize_for_match(term) in normalized for term in terms)


def _contains_no_any(answer: str, terms: list[str]) -> bool:
    normalized = _normalize_for_match(answer)
    return not any(_normalize_for_match(term) in normalized for term in terms)


def _regex_all(answer: str, patterns: list[str]) -> bool:
    normalized = _normalize_for_match(answer)
    return all(re.search(pattern, normalized, flags=re.IGNORECASE | re.MULTILINE) for pattern in patterns)


def _line_contains_doc_and_term(answer: str, doc: str, term: str) -> bool:
    normalized_doc = _normalize_for_match(doc)
    normalized_term = _normalize_for_match(term)
    normalized_lines = [_normalize_for_match(line) for line in answer.splitlines()]
    return any(normalized_doc in line and normalized_term in line for line in normalized_lines)


def _answer_contains_doc_and_term(answer: str, doc: str, term: str) -> bool:
    """expected_by_doc는 문서명 출처와 본문 값을 분리해 쓰는 정답도 허용한다."""

    normalized_doc = _normalize_for_match(doc)
    normalized_term = _normalize_for_match(term)
    normalized_answer = _normalize_for_match(answer)
    return _line_contains_doc_and_term(answer, doc, term) or (
        normalized_doc in normalized_answer and normalized_term in normalized_answer
    )


def _by_doc_ok(answer: str, expected_by_doc: dict[str, list[str]]) -> bool:
    for doc, terms in expected_by_doc.items():
        for term in terms:
            if not _answer_contains_doc_and_term(answer, doc, term):
                return False
    return True


def _forbidden_by_doc_ok(answer: str, forbidden_by_doc: dict[str, list[str]]) -> bool:
    for doc, terms in forbidden_by_doc.items():
        for term in terms:
            if _line_contains_doc_and_term(answer, doc, term):
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
    checks["required_any"] = True if not case.get("required_any") else _contains_any(answer, case["required_any"])
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


def classify_defect_type(case: dict[str, Any], checks: dict[str, bool], error_msg: str | None) -> str | None:
    if error_msg:
        err_lower = error_msg.lower()
        if any(w in err_lower for w in ("completions", "endpoint", "connection", "status", "서버", "호출", "timeout", "초과")):
            return "endpoint_error"
        return "script_error"

    if not checks.get("retrieval_expected_sources", True):
        return "retrieval_miss"
    if not checks.get("source_citation", True):
        return "citation_missing"
    if not checks.get("output_health", True):
        return "empty_or_bad_output"
    if not checks.get("no_evidence_warning", True):
        return "prompt_injection_followed"

    # HIRA 표 또는 코드 매치 오류 분별
    if not checks.get("required_terms", True) or not checks.get("required_any", True) or not checks.get("min_keyword_hits", True):
        case_id = case.get("id", "").lower()
        if any(w in case_id for w in ("hira", "code", "score", "grade", "disability", "three_nonpay")):
            return "wrong_code_or_score"
        return "wrong_doc_mix"

    if not checks.get("expected_by_doc", True) or not checks.get("forbidden_by_doc", True) or not checks.get("min_docs_in_answer", True):
        return "wrong_doc_mix"

    if not checks.get("forbidden_terms", True) or not checks.get("forbidden_any", True):
        case_id = case.get("id", "").lower()
        if "fake" in case_id:
            return "hallucinated_code"
        if "safe" in case_id or "injection" in case_id:
            return "prompt_injection_followed"
        if "overbroad" in case_id or "legal" in case_id:
            return "over_assertion"
        return "wrong_code_or_score"

    return None


def switch_model(model: str, command: str, timeout: int) -> None:
    started = time.perf_counter()
    completed = subprocess.run([command, model], text=True, capture_output=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        tail = (completed.stdout + "\n" + completed.stderr)[-4000:]
        raise RuntimeError(f"switch failed for {model} (exit={completed.returncode})\n{tail}")
    elapsed = time.perf_counter() - started
    print(f"[model] {model} active after {elapsed:.1f}s")


def validate_index_paths(index_mode: str) -> tuple[Path, Path]:
    """평가 실행 전에 BM25/Chroma 산출물이 모두 존재하는지 확인한다."""

    bm25_path, chroma_dir = resolve_index_paths(index_mode)
    if not bm25_path.exists():
        raise RuntimeError(f"BM25 인덱스가 없습니다: {bm25_path}")
    chroma_sqlite = chroma_dir / "chroma.sqlite3"
    if not chroma_sqlite.exists():
        raise RuntimeError(f"Chroma 인덱스가 없습니다: {chroma_sqlite}")
    return bm25_path, chroma_dir


def make_pipeline(
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    max_tokens: int,
    index_mode: str,
    embedder_device: str,
) -> RagPipeline:
    llm = OpenAICompatibleClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
        max_tokens=max_tokens,
        provider=provider,
    )

    # served model 확인
    served_models = llm.list_models()
    if model not in served_models:
        raise RuntimeError(
            f"{provider.upper()} 서버가 작동 중이나 모델 {model!r}이 서빙 중이지 않습니다. served={served_models}"
        )

    # 인덱스 경로 설정
    bm25_path, chroma_dir = validate_index_paths(index_mode)

    if embedder_device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    embedder = Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
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


def retrieve_only_hits(pipeline: RagPipeline, question: str, top_k: int, doc_filter: list[str] | None):
    """LLM 없이 현재 RagPipeline의 GraphDB 보강 검색 경로를 최대한 동일하게 실행한다."""

    graph_hits = []
    if getattr(pipeline, "graph_enabled", False) and getattr(pipeline, "graph_retriever", None):
        try:
            graph_result = pipeline.graph_retriever.retrieve(question)
            source_chunk_ids = getattr(graph_result, "source_chunk_ids", [])
            if source_chunk_ids:
                graph_hits = pipeline.vector_store.get_by_ids(source_chunk_ids)
        except Exception as exc:
            print(f"[Graph Warning] retrieval-only graph lookup failed: {exc}")
            graph_hits = []
    hits, _ = pipeline.retrieve_hits(question, top_k=top_k, doc_filter=doc_filter, graph_hits=graph_hits)
    return hits


def main():
    parser = argparse.ArgumentParser(description="Evaluate chatbot Model x Index Matrix.")
    parser.add_argument("--cases", type=Path, default=ROOT / "eval" / "chatbot_qa_stage2.jsonl")
    parser.add_argument("--models", type=str, default="gemma4_vllm,gpt_oss_sglang", help="Comma-separated model keys")
    parser.add_argument("--index-modes", type=str, default="default,v2_only,v1_v2_combined", help="Comma-separated index modes")
    parser.add_argument("--review-types", type=str, default="auto", help="Comma-separated review types: auto,manual or all")
    parser.add_argument("--difficulty", type=str, default="all", help="Comma-separated difficulty values: smoke,standard,hard or all")
    parser.add_argument("--category", type=str, default="all", help="all or comma-separated categories")
    parser.add_argument("--ids", type=str, default="", help="comma-separated exact case IDs")
    parser.add_argument("--limit", type=int, default=0, help="max cases to run per matrix slot")
    parser.add_argument("--retrieval-only", action="store_true", help="evaluate retrieval only (no LLM)")
    parser.add_argument("--no-switch", action="store_true", help="skip model switching commands")
    parser.add_argument("--label", type=str, default="matrix_eval")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "chatbot_model_index_matrix")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--embedder-device", type=str, default="cpu")
    parser.add_argument("--switch-command", type=str, default="")
    parser.add_argument("--switch-timeout", type=int, default=0)
    args = parser.parse_args()

    # 파라미터 리스트 파싱
    target_model_keys = _split_csv(args.models)
    target_index_modes = _split_csv(args.index_modes)
    selected_review_types = _split_csv(args.review_types, ["auto"])
    selected_difficulties = _split_csv(args.difficulty, ["all"])

    # 케이스 로드 및 필터링
    if not args.cases.exists():
        print(f"[Error] Cases file not found: {args.cases}")
        sys.exit(1)
    all_cases = load_cases(args.cases)

    filtered_cases = []
    selected_ids = _split_csv(args.ids)
    selected_categories = _split_csv(args.category, ["all"])

    for case in all_cases:
        # ID 필터
        if selected_ids and case.get("id") not in selected_ids:
            continue
        # Review Type 필터
        if not _matches_filter(case.get("review_type"), selected_review_types):
            continue
        # Difficulty 필터
        if not _matches_filter(case.get("difficulty"), selected_difficulties):
            continue
        # Category 필터
        if not _matches_filter(case.get("category"), selected_categories):
            continue
        filtered_cases.append(case)

    if args.limit > 0:
        filtered_cases = filtered_cases[:args.limit]

    print(f"[Matrix] Loaded {len(filtered_cases)} cases for evaluation.")
    if not filtered_cases:
        print("[Matrix] No eligible cases found. Exiting.")
        return

    # 실행 매트릭스 리스트 구성
    results: list[CaseResult] = []

    for model_key in target_model_keys:
        if model_key not in MODEL_CONFIGS:
            print(f"[Warning] Unknown model key: {model_key}")
            continue
        m_cfg = MODEL_CONFIGS[model_key]

        # 1. 모델 스위치 수행 (no-switch가 꺼져있을 때만)
        if not args.no_switch:
            cmd = args.switch_command or m_cfg["switch_command"]
            timeout = args.switch_timeout or m_cfg["switch_timeout"]
            try:
                switch_model(m_cfg["model"], cmd, timeout)
            except Exception as exc:
                print(f"[Switch Error] Failed to switch to model {model_key}: {exc}")
                # 이 모델 아래의 모든 조합을 ERROR 처리
                for index_mode in target_index_modes:
                    matrix_id = matrix_id_for(index_mode, m_cfg["provider"], m_cfg["model"])
                    for case in filtered_cases:
                        results.append(CaseResult(
                            label=args.label,
                            case_id=case["id"],
                            category=case.get("category", ""),
                            question=case["question"],
                            difficulty=case.get("difficulty", ""),
                            review_type=case.get("review_type", ""),
                            index_mode=index_mode,
                            matrix_id=matrix_id,
                            provider=m_cfg["provider"],
                            model=m_cfg["model"],
                            eligible=True,
                            passed=False,
                            checks={},
                            failures=["exception"],
                            answer="",
                            top_sources=[],
                            timing={"elapsed_s": 0.0},
                            defect_type="endpoint_error",
                            error=f"Model switch failed: {exc}",
                        ))
                continue

        # 2. 각 인덱스 모드별로 RAG 파이프라인 가동 후 실행
        for index_mode in target_index_modes:
            matrix_id = matrix_id_for(index_mode, m_cfg["provider"], m_cfg["model"])
            pipeline = None
            try:
                if not args.retrieval_only:
                    pipeline = make_pipeline(
                        provider=m_cfg["provider"],
                        model=m_cfg["model"],
                        base_url=m_cfg["base_url"],
                        api_key=m_cfg["api_key"],
                        max_tokens=args.max_tokens,
                        index_mode=index_mode,
                        embedder_device=args.embedder_device
                    )
                else:
                    # retrieval-only 일때는 LLM 없이 RAG 리트리버만 동적 셋업
                    bm25_path, chroma_dir = validate_index_paths(index_mode)
                    embedder = Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
                    vector_store = VectorStore(chroma_dir)
                    bm25 = BM25Index.load(bm25_path)
                    pipeline = RagPipeline(
                        embedder=embedder,
                        vector_store=vector_store,
                        bm25=bm25,
                        llm=None,
                        top_k_dense=config.TOP_K_DENSE,
                        top_k_bm25=config.TOP_K_BM25,
                        top_k_final=config.TOP_K_FINAL,
                        rrf_k=config.RRF_K,
                    )
            except Exception as exc:
                print(f"[Pipeline Error] {model_key} + {index_mode} RAG 셋업 실패: {exc}")
                # 이 조합의 모든 케이스를 ERROR 처리
                for case in filtered_cases:
                    results.append(CaseResult(
                        label=args.label,
                        case_id=case["id"],
                        category=case.get("category", ""),
                        question=case["question"],
                        difficulty=case.get("difficulty", ""),
                        review_type=case.get("review_type", ""),
                        index_mode=index_mode,
                        matrix_id=matrix_id,
                        provider=m_cfg["provider"],
                        model=m_cfg["model"],
                        eligible=True,
                        passed=False,
                        checks={},
                        failures=["exception"],
                        answer="",
                        top_sources=[],
                        timing={"elapsed_s": 0.0},
                        defect_type="endpoint_error",
                        error=f"Pipeline setup failed: {exc}",
                    ))
                continue

            # 각 케이스별 평가 수행
            for idx_c, case in enumerate(filtered_cases, start=1):
                started = time.perf_counter()

                # eligibility 체크
                case_index_modes = case.get("index_modes", [])
                # 만약 case에 index_modes가 명시되어 있고 현재 index_mode가 포함되어 있지 않다면 SKIP
                if case_index_modes and index_mode not in case_index_modes:
                    results.append(CaseResult(
                        label=args.label,
                        case_id=case["id"],
                        category=case.get("category", ""),
                        question=case["question"],
                        difficulty=case.get("difficulty", ""),
                        review_type=case.get("review_type", ""),
                        index_mode=index_mode,
                        matrix_id=matrix_id,
                        provider=m_cfg["provider"],
                        model=m_cfg["model"],
                        eligible=False,
                        passed=True, # skip은 pass로 보거나 pivot에서 SKIP 마킹
                        checks={},
                        failures=[],
                        answer="[SKIPPED]",
                        top_sources=[],
                        timing={"elapsed_s": 0.0},
                        defect_type=None,
                    ))
                    continue

                try:
                    if args.retrieval_only:
                        # LLM 없이 retrieve 기능만 가동
                        hits = retrieve_only_hits(
                            pipeline,
                            case["question"],
                            top_k=args.top_k,
                            doc_filter=case.get("doc_sources"),
                        )
                        expected_sources = case.get("expected_sources", [])
                        retrieval_ok = case.get("allow_retrieval_miss", False) or _expected_source_recall(hits, expected_sources)

                        checks = {
                            "retrieval_expected_sources": retrieval_ok,
                            "source_citation": True,
                            "output_health": True,
                            "no_evidence_warning": True,
                            "required_terms": True,
                            "required_any": True,
                            "forbidden_terms": True,
                            "forbidden_any": True,
                            "required_regex": True,
                            "expected_by_doc": True,
                            "forbidden_by_doc": True,
                            "min_docs_in_answer": True,
                            "min_keyword_hits": True,
                        }
                        failures = [] if retrieval_ok else ["retrieval_expected_sources"]
                        answer_text = "[Retrieval Only Mode]"
                        top_sources_data = _top_sources(hits)
                        timing_data = {"elapsed_s": time.perf_counter() - started}
                    else:
                        # RAG answer 가동
                        answer = pipeline.answer(
                            case["question"],
                            temperature=args.temperature,
                            top_k=args.top_k,
                            doc_filter=case.get("doc_sources"),
                            return_debug=False,
                        )
                        checks, failures = evaluate_answer(case, answer.answer, answer.chunks)
                        answer_text = answer.answer
                        top_sources_data = _top_sources(answer.chunks)
                        timing_data = {**answer.timing, "elapsed_s": time.perf_counter() - started}

                    passed = not failures
                    defect_type = classify_defect_type(case, checks, None) if not passed else None

                    results.append(CaseResult(
                        label=args.label,
                        case_id=case["id"],
                        category=case.get("category", ""),
                        question=case["question"],
                        difficulty=case.get("difficulty", ""),
                        review_type=case.get("review_type", ""),
                        index_mode=index_mode,
                        matrix_id=matrix_id,
                        provider=m_cfg["provider"],
                        model=m_cfg["model"],
                        eligible=True,
                        passed=passed,
                        checks=checks,
                        failures=failures,
                        answer=answer_text,
                        top_sources=top_sources_data,
                        timing=timing_data,
                        defect_type=defect_type,
                    ))

                except Exception as exc:
                    elapsed = time.perf_counter() - started
                    defect_type = "endpoint_error"
                    results.append(CaseResult(
                        label=args.label,
                        case_id=case["id"],
                        category=case.get("category", ""),
                        question=case["question"],
                        difficulty=case.get("difficulty", ""),
                        review_type=case.get("review_type", ""),
                        index_mode=index_mode,
                        matrix_id=matrix_id,
                        provider=m_cfg["provider"],
                        model=m_cfg["model"],
                        eligible=True,
                        passed=False,
                        checks={},
                        failures=["exception"],
                        answer="",
                        top_sources=[],
                        timing={"elapsed_s": elapsed},
                        defect_type=defect_type,
                        error=str(exc),
                    ))

                # 진행 로그 콘솔 출력
                last_res = results[-1]
                status_str = "PASS" if last_res.passed else "FAIL"
                err_suffix = f" error={last_res.error[:80]}" if last_res.error else ""
                fail_suffix = f" failures={','.join(last_res.failures)}" if last_res.failures else ""
                print(f"[{model_key} | {index_mode}] ({idx_c:02d}/{len(filtered_cases)}) {status_str} {last_res.case_id}{fail_suffix}{err_suffix}")

    # 리포트 출력
    write_reports(results, args.report_dir, args.label)


def write_reports(results: list[CaseResult], report_dir: Path, label: str) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = report_dir / f"matrix_{label}.jsonl"
    md_path = report_dir / f"matrix_{label}.md"
    failures_path = report_dir / f"matrix_{label}_failures.md"
    pivot_path = report_dir / f"matrix_{label}_pivot.csv"

    # 1. JSONL 원시 로그 저장
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    print(f"[Matrix] JSONL saved to {jsonl_path}")

    # 2. 피봇 테이블 CSV 생성
    matrix_ids = list(MATRIX_COLUMNS)

    # case_id 기준으로 묶음
    pivot_data: dict[str, dict[str, Any]] = {}
    for r in results:
        cid = r.case_id
        if cid not in pivot_data:
            pivot_data[cid] = {
                "case_id": cid,
                "category": r.category,
                "difficulty": r.difficulty,
                "review_type": r.review_type,
                "question": r.question,
            }

        if not r.eligible:
            cell_val = "SKIP:not_eligible"
        elif r.error:
            cell_val = f"ERROR:{r.error[:80].replace(',', ';')}"
        elif r.passed:
            cell_val = "PASS"
        else:
            failures_str = "|".join(r.failures) if r.failures else "unknown"
            cell_val = f"FAIL:{failures_str}"

        pivot_data[cid][r.matrix_id] = cell_val

    # CSV 출력
    csv_headers = ["case_id", "category", "difficulty", "review_type"] + matrix_ids
    with pivot_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(csv_headers)
        for cid, row in pivot_data.items():
            line_row = [
                row.get("case_id"),
                row.get("category"),
                row.get("difficulty"),
                row.get("review_type"),
            ]
            for mid in matrix_ids:
                line_row.append(row.get(mid, "SKIP:not_eligible"))
            writer.writerow(line_row)
    print(f"[Matrix] CSV Pivot saved to {pivot_path}")

    # 3. 마크다운 보고서 생성
    total_runs = sum(1 for r in results if r.eligible)
    passed_runs = sum(1 for r in results if r.eligible and r.passed and not r.error)
    total_errors = sum(1 for r in results if r.eligible and r.error)
    weighted_earned, weighted_total, weighted_rate = weighted_score(results)

    global_pass_rate = (passed_runs / total_runs * 100) if total_runs else 0.0

    lines = [
        f"# Chatbot Model x Index Matrix Evaluation Report (label: {label})",
        "",
        f"* **Generated At**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"* **Global Pass Rate**: `{passed_runs}/{total_runs} ({global_pass_rate:.1f}%)`",
        f"* **Weighted Quality Score**: `{weighted_earned}/{weighted_total} ({weighted_rate:.1f}점)`",
        f"* **Global Errors**: `{total_errors}`",
        "",
        "## 1. 다차원 품질 매트릭스 통계",
        "",
    ]

    # 모델별 통계
    lines.append("### 1.1 모델별 합격률 (Pass Rate)")
    lines.append("| 모델 (Provider) | 실행 수 | 패스 수 | 에러 수 | 패스율 |")
    lines.append("| --- | --- | --- | --- | --- |")

    by_model: dict[str, list[CaseResult]] = {}
    for r in results:
        key = f"{r.provider}:{r.model}"
        by_model.setdefault(key, []).append(r)

    for model_key, m_runs in sorted(by_model.items()):
        eli_runs = [r for r in m_runs if r.eligible]
        tot = len(eli_runs)
        pas = sum(1 for r in eli_runs if r.passed and not r.error)
        err = sum(1 for r in eli_runs if r.error)
        p_rate = (pas / tot * 100) if tot else 0.0
        lines.append(f"| `{model_key}` | {tot} | {pas} | {err} | **{p_rate:.1f}%** |")
    lines.append("")

    # 인덱스별 통계
    lines.append("### 1.2 인덱스 모드별 합격률 (Pass Rate)")
    lines.append("| 인덱스 모드 | 실행 수 | 패스 수 | 에러 수 | 패스율 |")
    lines.append("| --- | --- | --- | --- | --- |")

    by_index: dict[str, list[CaseResult]] = {}
    for r in results:
        by_index.setdefault(r.index_mode, []).append(r)

    for idx_key, idx_runs in sorted(by_index.items()):
        eli_runs = [r for r in idx_runs if r.eligible]
        tot = len(eli_runs)
        pas = sum(1 for r in eli_runs if r.passed and not r.error)
        err = sum(1 for r in eli_runs if r.error)
        p_rate = (pas / tot * 100) if tot else 0.0
        lines.append(f"| `{idx_key}` | {tot} | {pas} | {err} | **{p_rate:.1f}%** |")
    lines.append("")

    # 카테고리별 통계
    lines.append("### 1.3 카테고리별 합격률 (Pass Rate)")
    lines.append("| 카테고리 | 가중치 | 실행 수 | 패스 수 | 패스율 |")
    lines.append("| --- | --- | --- | --- | --- |")

    by_cat: dict[str, list[CaseResult]] = {}
    for r in results:
        if r.eligible:
            by_cat.setdefault(r.category, []).append(r)

    for cat_key, cat_runs in sorted(by_cat.items()):
        tot = len(cat_runs)
        pas = sum(1 for r in cat_runs if r.passed and not r.error)
        p_rate = (pas / tot * 100) if tot else 0.0
        lines.append(f"| `{cat_key}` | {score_weight_for_category(cat_key)} | {tot} | {pas} | **{p_rate:.1f}%** |")
    lines.append("")

    # 4. Defect Type 결함 분석 요약
    lines.append("## 2. 결함 유형(Defect Type) 분석 요약")
    lines.append("")
    lines.append("| 결함 유형 (Defect Type) | 감지 횟수 | 설명 |")
    lines.append("| --- | --- | --- |")

    defect_counts: dict[str, int] = {
        "retrieval_miss": 0,
        "wrong_doc_mix": 0,
        "wrong_code_or_score": 0,
        "neighbor_row_mix": 0,
        "v1_override_v2": 0,
        "citation_missing": 0,
        "citation_wrong_page": 0,
        "hallucinated_code": 0,
        "over_assertion": 0,
        "prompt_injection_followed": 0,
        "empty_or_bad_output": 0,
        "endpoint_error": 0,
        "script_error": 0,
    }
    for r in results:
        if r.eligible and not r.passed and r.defect_type:
            defect_counts[r.defect_type] = defect_counts.get(r.defect_type, 0) + 1

    descriptions = {
        "retrieval_miss": "검색 기대 출처(expected source page) 누락",
        "wrong_doc_mix": "심평원/약관/실무가이드/사례집 정보 오용 및 혼용",
        "wrong_code_or_score": "코드, 점수, 지급률, 종수 등 핵심 수치 오류",
        "neighbor_row_mix": "표의 위아래 행 수치 섞임",
        "v1_override_v2": "원본 OCR이 보정본 결론을 덮어씀",
        "citation_missing": "출처 표기([출처: ...]) 생략 및 누락",
        "citation_wrong_page": "출처 페이지 기재 오류",
        "hallucinated_code": "없는 가짜 코드를 사실인 것처럼 환각 생성",
        "over_assertion": "약관상 가부를 불확실성 표현 없이 무조건 단정",
        "prompt_injection_followed": "출처 무시 등 우회 악성 프롬프트 지시 순응",
        "empty_or_bad_output": "빈 본문 또는 <pad> 특수 토큰 반복 다량 노출",
        "endpoint_error": "LLM API 엔드포인트 호출/연동 예외 초과",
        "script_error": "평가 스크립트 런타임 오류",
    }
    for d_type, cnt in sorted(defect_counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| `{d_type}` | **{cnt}** | {descriptions.get(d_type, '-')} |")
    lines.append("")

    # 5. 동일 질문 모델간 / 인덱스간 차이 비교 분석
    lines.append("## 3. 동일 질문 매트릭스 차이 분석")
    lines.append("")
    lines.append("동일 질문에서 모델 간(vLLM vs SGLang) 또는 인덱스 간(default vs v2 vs combined) 결과 판단의 불일치가 감지된 문항 요약입니다.")
    lines.append("")

    # pivot 데이터를 돌며 불일치 체크
    diff_count = 0
    lines.append("| 문항 ID | 질문 (Question) | 불일치 매트릭스 목록 |")
    lines.append("| --- | --- | --- |")
    for cid, row in sorted(pivot_data.items()):
        all_vals = [row.get(mid) for mid in matrix_ids if row.get(mid) is not None]
        # PASS와 FAIL/ERROR가 섞여있으면 불일치
        has_pass = any("PASS" in v for v in all_vals)
        has_fail = any("FAIL" in v or "ERROR" in v for v in all_vals)
        if has_pass and has_fail:
            diff_count += 1
            matrix_summary = []
            for mid in matrix_ids:
                val = row.get(mid, "SKIP")
                if "PASS" in val or "FAIL" in val or "ERROR" in val:
                    # 간단 표기
                    matrix_summary.append(f"{mid.split('__')[0]}: `{val}`")
            lines.append(f"| `{cid}` | {row.get('question')[:80]}... | {', '.join(matrix_summary)} |")

    if diff_count == 0:
        lines.append("*(비교 가능한 다중 실행 매트릭스가 없거나 모든 실행 결과가 완벽하게 일치합니다.)*")
    lines.append("")

    # 파일 라이트
    with md_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[Matrix] Markdown summary saved to {md_path}")

    # 4. 오답 전용 상세 분석 보고서(failures.md) 생성
    fail_lines = [
        f"# Chatbot Matrix Evaluation Failure Details (label: {label})",
        "",
        "본 문서는 매트릭스 평가 중 PASS 기준을 만족하지 못했거나 오류(ERROR)를 유발한 문항에 대한 심층 오답 보고서입니다.",
        "",
    ]

    failed_runs = [r for r in results if r.eligible and (not r.passed or r.error)]
    for idx, fr in enumerate(failed_runs, start=1):
        fail_lines.extend([
            f"### {idx}. [{fr.case_id}] (인덱스: `{fr.index_mode}` | 모델: `{fr.provider}:{fr.model}`)",
            f"* **Category**: `{fr.category}` | **Difficulty**: `{fr.difficulty}`",
            f"* **Defect Type**: `{fr.defect_type}`",
            f"* **Failed Checklists**: `{', '.join(fr.failures) or '-'}`",
            f"* **Question**: {fr.question}",
        ])
        if fr.error:
            fail_lines.append(f"* **Error Details**: `{fr.error}`")
        if fr.answer:
            fail_lines.extend([
                "* **Generated Answer**:",
                "```text",
                fr.answer,
                "```",
            ])
        if fr.top_sources:
            fail_lines.append("* **Top Retrieved Sources (Chunks)**:")
            for s_idx, src in enumerate(fr.top_sources, start=1):
                fail_lines.append(f"  - [{s_idx}] [{src.get('doc_short')}] p.{src.get('page_start')}~{src.get('page_end')}: *\"{src.get('preview')}\"*")
        fail_lines.append("---")
        fail_lines.append("")

    if not failed_runs:
        fail_lines.append("*(축하합니다! 실패하거나 에러가 발생한 매트릭스 문항이 단 하나도 없습니다.)*")

    with failures_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(fail_lines))
    print(f"[Matrix] Markdown failures saved to {failures_path}")


if __name__ == "__main__":
    main()
