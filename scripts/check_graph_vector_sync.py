"""GraphDB evidence와 Chroma VectorStore의 근거 청크 정합성을 진단한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src import config
from src.graph.vector_sync import build_report, check_evidence_sync, load_evidence_rows
from src.retrieval.index_mode import INDEX_MODES, resolve_index_paths
from src.retrieval.vector_store import VectorStore


def print_summary(report: dict) -> None:
    summary = report["summary"]
    counts = summary["status_counts"]
    print("GraphDB evidence / VectorStore sync diagnostic")
    print(f"- index_mode: {report['index_mode']}")
    print(f"- graph: {report['graph_path']}")
    print(f"- chroma: {report['chroma_dir']}")
    print(f"- sampled: {report['sampled_evidence_rows']}")
    print(f"- hit_rate: {summary['hit_rate']:.2%}")
    print(f"- direct_hit: {counts.get('direct_hit', 0)}")
    print(f"- canonical_chunk_hit: {counts.get('canonical_chunk_hit', 0)}")
    print(f"- source_chunk_hit: {counts.get('source_chunk_hit', 0)}")
    print(f"- fallback_hit: {counts.get('fallback_hit', 0)}")
    print(f"- doc_page_hit: {counts.get('doc_page_hit', 0)}")
    print(f"- missing: {counts.get('missing', 0)}")

    missing_docs = sorted(
        summary["by_doc_short"].items(),
        key=lambda item: item[1].get("missing", 0),
        reverse=True,
    )[:5]
    if missing_docs:
        print("- top_missing_docs:")
        for doc_short, doc_summary in missing_docs:
            print(f"  - {doc_short}: {doc_summary.get('missing', 0)} / {doc_summary.get('total', 0)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=config.GRAPH_INDEX_PATH)
    parser.add_argument("--index-mode", choices=INDEX_MODES, default="default")
    parser.add_argument("--chroma-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=1000, help="샘플 evidence 수. 0 이하면 전체 검사.")
    parser.add_argument("--seed", type=int, default=20260531)
    parser.add_argument("--doc-short", default=None)
    parser.add_argument("--source-method", default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--example-limit", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    graph_path = args.graph
    if args.chroma_dir is not None:
        chroma_dir = args.chroma_dir
    else:
        _, chroma_dir = resolve_index_paths(args.index_mode)

    limit = args.limit if args.limit and args.limit > 0 else None
    rows = load_evidence_rows(
        graph_path,
        limit=limit,
        seed=args.seed,
        doc_short=args.doc_short,
        source_method=args.source_method,
    )
    store = VectorStore(chroma_dir)
    results = check_evidence_sync(rows, store.collection)
    report = build_report(
        graph_path=graph_path,
        chroma_dir=chroma_dir,
        index_mode=args.index_mode,
        rows=rows,
        results=results,
        example_limit=args.example_limit,
    )
    print_summary(report)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
