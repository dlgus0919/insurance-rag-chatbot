#!/usr/bin/env python3
"""Graph RAG Retrieval Layer Automated Evaluation Script.

Evaluates GraphRetriever output against a predefined test dataset (eval/graph_qa.jsonl)
without invoking any LLM APIs. Checks intents, entities, facts, and statuses.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any

from src.graph.retriever import GraphRetriever, GraphFact, GraphRetrievalResult


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate Graph RAG Retrieval Layer.")
    parser.add_argument(
        "--graph",
        type=str,
        default="data/index/graph/insurance_graph.sqlite",
        help="Path to the SQLite Graph database file.",
    )
    parser.add_argument(
        "--eval",
        type=str,
        default="eval/graph_qa.jsonl",
        help="Path to the evaluation jsonl file.",
    )
    return parser.parse_args()


def match_fact(expected: Dict[str, Any], retrieved_facts: List[GraphFact]) -> bool:
    """Checks if expected fact matches any retrieved fact."""
    for f in retrieved_facts:
        if f.subject != expected.get("subject"):
            continue
        if f.relation != expected.get("relation"):
            continue
        if "object" in expected and f.object != expected["object"]:
            continue
        if "status" in expected and f.status != expected["status"]:
            continue

        # properties_contains 검증
        if "properties_contains" in expected:
            prop_match = True
            for k, v in expected["properties_contains"].items():
                if k not in f.properties or f.properties[k] != v:
                    prop_match = False
                    break
            if not prop_match:
                continue

        # requires_evidence 검증
        if expected.get("requires_evidence") and not f.evidence:
            continue

        if "requires_evidence_source_version" in expected:
            source_version = expected["requires_evidence_source_version"]
            if not any(getattr(ev, "source_version", None) == source_version for ev in f.evidence):
                continue

        return True
    return False


def run_evaluation(graph_path: Path, eval_path: Path) -> bool:
    if not graph_path.exists():
        print(f"Error: Graph database file not found at: {graph_path}")
        return False
    if not eval_path.exists():
        print(f"Error: Evaluation dataset file not found at: {eval_path}")
        return False

    print(f"Loading GraphRetriever with DB: {graph_path}")
    retriever = GraphRetriever(graph_path)

    cases = []
    with open(eval_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    print(f"Loaded {len(cases)} evaluation test cases from {eval_path}\n")

    # 결과 저장을 위한 디렉토리 생성
    report_dir = Path("reports/graph")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file_path = report_dir / "eval_graph_qa_results.jsonl"

    # 기존 파일 삭제 또는 초기화
    with open(report_file_path, "w", encoding="utf-8") as rf:
        pass

    all_passed = True
    passed_count = 0

    for idx, case in enumerate(cases, start=1):
        case_id = case.get("id", f"case_{idx}")
        question = case["question"]
        expected_intents = case.get("expected_intents", [])
        expected_entities = case.get("expected_entities", {})
        expected_facts = case.get("expected_facts", [])

        print(f"[{idx}/{len(cases)}] Evaluating case: {case_id}")
        print(f"  Query: \"{question}\"")

        # Run retrieval
        try:
            result: GraphRetrievalResult = retriever.retrieve(question)
        except Exception as e:
            print(f"  FAIL: Retrieval failed with exception: {e}")
            all_passed = False
            continue

        case_passed = True
        failures = []

        # 1. Verify intents
        for intent in expected_intents:
            if intent not in result.plan.intents:
                case_passed = False
                failures.append(f"Expected intent '{intent}' not found in matched intents: {result.plan.intents}")

        # 2. Verify entities
        for ent_key, ent_val in expected_entities.items():
            actual_val = getattr(result.plan, ent_key, None)
            if actual_val != ent_val:
                case_passed = False
                failures.append(f"Expected entity {ent_key}='{ent_val}', got '{actual_val}'")

        # 2.1 Verify forbidden facts
        forbidden_facts = case.get("forbidden_facts", [])
        for ff in forbidden_facts:
            for f in result.facts:
                if f.subject == ff.get("subject") and f.relation == ff.get("relation"):
                    if "object" not in ff or f.object == ff["object"]:
                        case_passed = False
                        failures.append(f"Forbidden fact found: {f.subject} --({f.relation})--> {f.object}")

        # 2.2 Verify max facts by relation
        max_facts_by_relation = case.get("max_facts_by_relation", {})
        relation_counts = {}
        for f in result.facts:
            relation_counts[f.relation] = relation_counts.get(f.relation, 0) + 1
        for rel, max_limit in max_facts_by_relation.items():
            actual_count = relation_counts.get(rel, 0)
            if actual_count > max_limit:
                case_passed = False
                failures.append(f"Relation '{rel}' count {actual_count} exceeded limit {max_limit}")

        # 2.3 Verify requires evidence for status
        requires_evidence_for_status = case.get("requires_evidence_for_status", [])
        for f in result.facts:
            if f.status in requires_evidence_for_status:
                if not f.evidence:
                    case_passed = False
                    failures.append(f"Fact '{f.subject} --({f.relation})--> {f.object}' has status '{f.status}' but lacks evidence.")

        # 2.4 Verify evidence source version for status
        source_version_by_status = case.get("requires_evidence_source_version_for_status", {})
        for f in result.facts:
            required_source_version = source_version_by_status.get(f.status)
            if required_source_version and not any(getattr(ev, "source_version", None) == required_source_version for ev in f.evidence):
                case_passed = False
                failures.append(
                    f"Fact '{f.subject} --({f.relation})--> {f.object}' has status '{f.status}' "
                    f"but lacks {required_source_version} evidence."
                )

        # 3. Verify missing fact constraint (missing fact must not have arbitrary object)
        for f in result.facts:
            if f.status == "missing" and f.object is not None and f.object != "":
                case_passed = False
                failures.append(f"Retrieved fact with status 'missing' has non-None object '{f.object}': {f.subject} --({f.relation})--> {f.object}")

        # 4. Verify expected facts
        for exp_fact in expected_facts:
            # Check structural match first to detect status mismatches
            structural_match = None
            for f in result.facts:
                if f.subject == exp_fact.get("subject") and f.relation == exp_fact.get("relation"):
                    if "object" not in exp_fact or f.object == exp_fact["object"]:
                        structural_match = f
                        break

            if structural_match:
                if "status" in exp_fact and structural_match.status != exp_fact["status"]:
                    case_passed = False
                    failures.append(
                        f"Fact status mismatch: {exp_fact.get('subject')} --({exp_fact.get('relation')})--> {exp_fact.get('object')}. "
                        f"Expected status '{exp_fact['status']}', but got '{structural_match.status}'."
                    )
                    if exp_fact["status"] == "candidate" and structural_match.status == "confirmed":
                        failures.append("    (Violation: Candidate fact was promoted to confirmed!)")
                    continue

            if not match_fact(exp_fact, result.facts):
                case_passed = False
                failures.append(f"Expected fact not matched: {exp_fact}")

        # Save actual results to JSONL
        case_result = {
            "case_id": case_id,
            "question": question,
            "intents": result.plan.intents,
            "entities": {
                "procedure_name": result.plan.procedure_name,
                "grade_system": result.plan.grade_system,
                "grade_value": result.plan.grade_value,
                "category": result.plan.category,
                "policy_product": result.plan.policy_product,
                "appendix": result.plan.appendix,
                "appendix_numbers": result.plan.appendix_numbers,
                "hira_code": result.plan.hira_code
            },
            "facts": [
                {
                    "subject": f.subject,
                    "relation": f.relation,
                    "object": f.object,
                    "status": f.status,
                    "confidence": f.confidence,
                    "properties": f.properties,
                    "has_evidence": len(f.evidence) > 0,
                    "evidence_source_versions": [
                        getattr(ev, "source_version", None) for ev in f.evidence
                    ],
                } for f in result.facts
            ]
        }
        with open(report_file_path, "a", encoding="utf-8") as rf:
            rf.write(json.dumps(case_result, ensure_ascii=False) + "\n")

        if case_passed:
            print("  PASS")
            passed_count += 1
        else:
            print("  FAIL:")
            for fail in failures:
                print(f"    - {fail}")
            print("  [DEBUG INFO - Actual Plan & Facts]")
            print(f"    - Intents: {result.plan.intents}")
            print(f"    - Entities: procedure_name={result.plan.procedure_name}, grade_system={result.plan.grade_system}, grade_value={result.plan.grade_value}, category={result.plan.category}, policy_product={result.plan.policy_product}, appendix={result.plan.appendix}, hira_code={result.plan.hira_code}")
            print("    - Facts:")
            for f in result.facts:
                print(f"      * {f.subject} --({f.relation})--> {f.object} (status: {f.status})")
            all_passed = False
        print()

    print("=" * 60)
    print(f"Evaluation Summary: {passed_count}/{len(cases)} cases passed.")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    args = parse_args()
    success = run_evaluation(Path(args.graph), Path(args.eval))
    sys.exit(0 if success else 1)
