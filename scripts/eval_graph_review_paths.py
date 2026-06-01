#!/usr/bin/env python3
"""Evaluate GraphDB review path behavior.

This evaluator checks structured graph paths rather than final LLM prose.
It intentionally fails on unsupported medical causality phrases and verifies
that review-oriented cases expose path/status/evidence/action signals.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src import config
from src.graph.retriever import GraphRetriever, GraphRetrievalResult


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def _flatten_result_text(result: GraphRetrievalResult) -> str:
    parts: list[str] = []
    plan = result.plan
    parts.extend(plan.intents or [])
    parts.extend(plan.diagnosis_codes or [])
    parts.extend(plan.coverage_topics or [])
    parts.extend(plan.conditions or [])
    for assertion in result.session_assertions:
        parts.extend([assertion.kind, assertion.value, assertion.notes])
    for path in result.review_paths:
        parts.extend([path.path_id, path.path_type, path.status, path.summary])
        parts.extend(path.required_evidence)
        parts.extend(path.review_actions)
        for step in path.steps:
            parts.extend([step.subject, step.relation, step.object or "", step.status, step.notes])
    return "\n".join(str(part) for part in parts if part is not None)


def _result_payload(result: GraphRetrievalResult) -> dict[str, Any]:
    return {
        "plan": asdict(result.plan),
        "session_assertions": [asdict(item) for item in result.session_assertions],
        "review_paths": [asdict(item) for item in result.review_paths],
        "required_evidence": result.required_evidence,
        "review_actions": result.review_actions,
        "warnings": result.warnings,
    }


def evaluate_case(case: dict[str, Any], result: GraphRetrievalResult) -> dict[str, Any]:
    failures: list[str] = []
    text = _flatten_result_text(result)
    path_types = {path.path_type for path in result.review_paths}
    statuses = {path.status for path in result.review_paths}
    assertion_values = {assertion.value for assertion in result.session_assertions}
    review_actions = {action for path in result.review_paths for action in path.review_actions}
    required_evidence = {
        item
        for path in result.review_paths
        for item in list(path.required_evidence or []) + list(path.required_documents or [])
    }
    rule_categories = {
        "exclusion_reasons": {item for path in result.review_paths for item in path.exclusion_reasons},
        "benefit_limits": {item for path in result.review_paths for item in path.benefit_limits},
        "deductible_rules": {item for path in result.review_paths for item in path.deductible_rules},
        "required_documents": {item for path in result.review_paths for item in path.required_documents},
        "coordination_rules": {item for path in result.review_paths for item in path.coordination_rules},
        "generation_rules": {item for path in result.review_paths for item in path.generation_rules},
    }
    plan_topics = set(result.plan.coverage_topics or [])
    plan_conditions = set(result.plan.conditions or [])
    plan_clarifications = set(result.plan.clarification_questions or [])
    plan_ambiguous_terms = set(result.plan.ambiguous_terms or [])
    normalized_terms = dict(result.plan.normalized_terms or {})
    term_correction_candidates = list(getattr(result.plan, "term_correction_candidates", []) or [])
    candidate_pairs = {
        (str(item.get("raw", "")), str(item.get("normalized", "")))
        for item in term_correction_candidates
    }

    for expected in case.get("expected_path_types", []):
        if expected not in path_types:
            failures.append(f"missing_path_type:{expected}")

    allowed_statuses = set(case.get("allowed_statuses", []))
    if allowed_statuses and statuses and not statuses.intersection(allowed_statuses):
        failures.append(f"status_not_allowed:{','.join(sorted(statuses))}")

    for expected in case.get("required_session_assertions", []):
        if expected not in assertion_values and expected not in text:
            failures.append(f"missing_session_assertion:{expected}")

    for expected in case.get("required_plan_topics", []):
        if expected not in plan_topics:
            failures.append(f"missing_plan_topic:{expected}")

    for expected in case.get("required_plan_conditions", []):
        if expected not in plan_conditions:
            failures.append(f"missing_plan_condition:{expected}")

    for expected in case.get("required_ambiguous_terms", []):
        if expected not in plan_ambiguous_terms:
            failures.append(f"missing_ambiguous_term:{expected}")

    any_clarifications = set(case.get("required_clarification_any", []))
    if any_clarifications and not any(
        expected in clarification
        for expected in any_clarifications
        for clarification in plan_clarifications
    ):
        failures.append(f"missing_clarification_any:{','.join(sorted(any_clarifications))}")

    for raw, expected in case.get("required_normalized_terms", {}).items():
        if normalized_terms.get(raw) != expected:
            failures.append(f"missing_normalized_term:{raw}->{expected}")

    for raw, expected in case.get("required_term_correction_candidates", {}).items():
        if (raw, expected) not in candidate_pairs:
            failures.append(f"missing_term_correction_candidate:{raw}->{expected}")

    any_actions = set(case.get("required_review_actions_any", []))
    if any_actions and not review_actions.intersection(any_actions):
        failures.append(f"missing_review_action_any:{','.join(sorted(any_actions))}")

    any_evidence = set(case.get("required_evidence_any", []))
    if any_evidence and not required_evidence.intersection(any_evidence):
        failures.append(f"missing_required_evidence_any:{','.join(sorted(any_evidence))}")

    for category, values in rule_categories.items():
        expected_any = set(case.get(f"required_{category}_any", []))
        if expected_any and not values.intersection(expected_any):
            failures.append(f"missing_{category}_any:{','.join(sorted(expected_any))}")
        for expected in case.get(f"required_{category}", []):
            if expected not in values:
                failures.append(f"missing_{category}:{expected}")

    for forbidden in case.get("forbidden_text", []):
        if forbidden and forbidden in text:
            failures.append(f"forbidden_text:{forbidden}")

    return {
        "id": case.get("id"),
        "question": case.get("question"),
        "passed": not failures,
        "failures": failures,
        "path_types": sorted(path_types),
        "statuses": sorted(statuses),
        "required_evidence": sorted(required_evidence),
        "review_actions": sorted(review_actions),
        "rule_categories": {key: sorted(values) for key, values in rule_categories.items()},
        "plan_topics": sorted(plan_topics),
        "plan_conditions": sorted(plan_conditions),
        "clarification_questions": sorted(plan_clarifications),
        "ambiguous_terms": sorted(plan_ambiguous_terms),
        "normalized_terms": normalized_terms,
        "term_correction_candidates": term_correction_candidates,
    }


def run_eval(graph_path: Path, eval_path: Path, output_path: Path | None = None) -> dict[str, Any]:
    retriever = GraphRetriever(graph_path)
    cases = _load_jsonl(eval_path)
    records: list[dict[str, Any]] = []

    for case in cases:
        result = retriever.retrieve(case["question"])
        record = evaluate_case(case, result)
        record["result"] = _result_payload(result)
        records.append(record)

    passed = sum(1 for record in records if record["passed"])
    summary = {
        "passed": passed,
        "total": len(records),
        "failed": len(records) - passed,
        "records": records,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GraphDB review path behavior.")
    parser.add_argument("--graph", type=Path, default=config.GRAPH_INDEX_PATH)
    parser.add_argument("--eval", type=Path, default=Path("eval/graph_review_paths.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/graph_review_paths/eval_graph_review_paths.jsonl"))
    args = parser.parse_args()

    summary = run_eval(args.graph, args.eval, args.output)
    print(f"Graph review path evaluation: {summary['passed']}/{summary['total']} passed")
    for record in summary["records"]:
        status = "PASS" if record["passed"] else "FAIL"
        print(f"- {status} {record['id']}")
        for failure in record["failures"]:
            print(f"  - {failure}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
