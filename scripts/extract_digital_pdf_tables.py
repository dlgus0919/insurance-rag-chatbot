#!/usr/bin/env python3
"""Extract text-layer tables from digital-born PDF sources."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.parser.digital_pdf_tables import (
    extract_digital_pdf_table_chunks,
    write_digital_pdf_table_artifacts,
)


def _select_sources(doc: str, doc_type: str) -> list[config.PdfSource]:
    sources = [
        source
        for source in config.PDF_SOURCES
        if not source.requires_ocr
        and source.path.exists()
        and (not doc_type or source.doc_type == doc_type)
    ]
    if doc != "all":
        sources = [source for source in sources if source.doc_short == doc]
    return sources


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", default="all", help="doc_short 또는 all")
    parser.add_argument(
        "--doc-type",
        default="insurance_policy",
        help="처리할 PdfSource.doc_type. 빈 문자열이면 모든 디지털 PDF.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=config.DIGITAL_PDF_TABLES_DIR,
        help="디지털 PDF table_json 산출물 루트.",
    )
    parser.add_argument("--min-rows", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_root = args.output_root if args.output_root.is_absolute() else ROOT / args.output_root
    summaries = []
    total_chunks = 0
    for source in _select_sources(args.doc, args.doc_type):
        chunks, summary = extract_digital_pdf_table_chunks(source, min_rows=args.min_rows)
        manifest_path = write_digital_pdf_table_artifacts(chunks, output_root, source.doc_short)
        total_chunks += len(chunks)
        summaries.append(
            {
                **summary.__dict__,
                "manifest": str(manifest_path),
            }
        )
    result = {
        "output_root": str(output_root),
        "source_count": len(summaries),
        "table_chunks": total_chunks,
        "sources": summaries,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
