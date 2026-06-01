#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.graph.build import build_graph

def main() -> None:
    parser = argparse.ArgumentParser(description="Build SQLite Property Graph index for insurance RAG.")
    parser.add_argument(
        "--chunks-path",
        type=str,
        default="data/processed/chunks_v1_v2_combined.jsonl",
        help="Path to combined chunks jsonl file."
    )
    parser.add_argument(
        "--canonical-manifest",
        type=str,
        default="data/processed/chunks_canonical_manifest.jsonl",
        help="Optional canonical manifest path. Used first for v2_only/v1_v2_combined when present.",
    )
    parser.add_argument(
        "--standard-code-db",
        type=str,
        default="data/index/relational/standard_codes.sqlite",
        help="Path to standard codes SQLite DB."
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/index/graph/insurance_graph.sqlite",
        help="Output SQLite path for property graph."
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default="data/index/graph/insurance_graph_manifest.json",
        help="Output JSON path for manifest."
    )
    parser.add_argument(
        "--low-confidence-report",
        type=str,
        default="reports/graph/graph_low_confidence_edges.jsonl",
        help="Output JSONL path for low confidence report."
    )
    parser.add_argument(
        "--source-mode",
        type=str,
        default="v1_v2_combined",
        choices=["default", "v2_only", "v1_v2_combined"],
        help="Source mode for chunking source."
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Whether to delete existing DB and rebuild from scratch."
    )
    parser.add_argument(
        "--skip-standard-codes",
        action="store_true",
        help="Skip ingesting standard codes."
    )
    parser.add_argument(
        "--skip-policy-appendix",
        action="store_true",
        help="Skip ingesting policy appendix rules."
    )
    parser.add_argument(
        "--skip-hira-codes",
        action="store_true",
        help="Skip ingesting HIRA codes."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode validation."
    )

    args = parser.parse_args()

    build_graph(
        chunks_path=args.chunks_path,
        standard_db_path=args.standard_code_db,
        output_db_path=args.output,
        manifest_path=args.manifest,
        low_confidence_report_path=args.low_confidence_report,
        canonical_manifest_path=args.canonical_manifest,
        source_mode=args.source_mode,
        rebuild=args.rebuild,
        skip_standard_codes=args.skip_standard_codes,
        skip_policy_appendix=args.skip_policy_appendix,
        skip_hira_codes=args.skip_hira_codes,
    )

if __name__ == "__main__":
    main()
