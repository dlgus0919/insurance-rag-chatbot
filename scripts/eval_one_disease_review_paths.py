#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src import config
from scripts.eval_graph_review_paths import run_eval


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate one-disease GraphRAG review path behavior.")
    parser.add_argument("--graph", type=Path, default=config.GRAPH_INDEX_PATH)
    parser.add_argument("--eval", type=Path, default=Path("eval/one_disease_review_paths.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/graph_review_paths/eval_one_disease_review_paths.jsonl"))
    args = parser.parse_args()

    summary = run_eval(args.graph, args.eval, args.output)
    print(f"One-disease review path evaluation: {summary['passed']}/{summary['total']} passed")
    for record in summary["records"]:
        status = "PASS" if record["passed"] else "FAIL"
        print(f"- {status} {record['id']}")
        for failure in record["failures"]:
            print(f"  - {failure}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
