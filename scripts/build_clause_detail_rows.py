#!/usr/bin/env python3
"""Build clause_detail_rows manifest from existing OCR table_json chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parser.chunker import Chunk
from src.parser.digital_pdf_tables import load_digital_pdf_table_chunks
from src import config
from src.rag.clause_detail_rows import (
    SCHEMA_VERSION,
    resolve_clause_detail_rows_path,
    resolve_clause_detail_source_chunks_path,
)
from src.rag.pipeline import (
    _clause_detail_row_items,
    _clause_detail_row_label,
    _clause_detail_source_parts,
    _extract_clause_detail_numbers,
    _extract_clause_detail_source_label,
    _load_clause_detail_table_json,
    _normalize_clause_detail_cell,
)
from src.retrieval.index_mode import INDEX_MODES


def _iter_chunk_records(path: Path):
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            payload = json.loads(line)
            metadata = payload.get("metadata") or {}
            yield Chunk(
                id=str(payload.get("id") or metadata.get("canonical_chunk_id") or ""),
                text=str(payload.get("text") or ""),
                metadata=metadata,
            )


def _row_id(chunk_id: str, row_index: int, value_text: str) -> str:
    digest = hashlib.sha1(f"{chunk_id}:{row_index}:{value_text}".encode("utf-8")).hexdigest()[:12]
    return f"cdr.{chunk_id}.{row_index}.{digest}"


def _build_record_from_chunk(chunk: Chunk, row_index: int, raw_row: Any, headers: list[Any]) -> dict[str, Any] | None:
    items = _clause_detail_row_items(raw_row, headers)
    if not items:
        return None
    row_label = _clause_detail_row_label(items)
    value_text = " | ".join(f"{header}: {value}" for header, value in items)
    numbers = _extract_clause_detail_numbers(value_text)
    metadata = chunk.metadata
    parent_heading = str(
        metadata.get("section")
        or metadata.get("chapter")
        or metadata.get("part")
        or ""
    )
    source_label = _extract_clause_detail_source_label(f"{parent_heading} {chunk.text}")
    article, table_label = _clause_detail_source_parts(source_label)
    return {
        "schema_version": SCHEMA_VERSION,
        "row_id": _row_id(chunk.id, row_index, value_text),
        "doc_short": str(metadata.get("doc_short") or "문서"),
        "article": article,
        "table_label": table_label,
        "page": metadata.get("page_start"),
        "chunk_id": chunk.id,
        "parent_heading": parent_heading,
        "row_label": row_label,
        "value_text": value_text,
        "numbers": numbers,
        "source_metadata": {
            "source": metadata.get("source_method") or "processed_chunks_table_json",
            "source_file": metadata.get("source_file"),
            "pdf_filename": metadata.get("pdf_filename"),
            "content_type": metadata.get("content_type"),
            "headers": [_normalize_clause_detail_cell(header) for header in headers],
            "row_index": row_index,
            "table_confidence": metadata.get("table_confidence"),
            "bbox": metadata.get("bbox"),
            "digital_table_schema_version": metadata.get("digital_table_schema_version"),
        },
    }


def _iter_table_chunks(chunks_path: Path, digital_table_root: Path | None):
    seen: set[str] = set()
    for chunk in _iter_chunk_records(chunks_path):
        seen.add(chunk.id)
        yield chunk, "processed"
    if digital_table_root is None:
        return
    for chunk in load_digital_pdf_table_chunks(digital_table_root):
        if chunk.id in seen:
            continue
        seen.add(chunk.id)
        yield chunk, "digital_pdf"


def build_clause_detail_rows(
    chunks_path: Path,
    output_path: Path,
    digital_table_root: Path | None = None,
) -> dict[str, int]:
    rows_written = 0
    chunks_seen = 0
    table_chunks_seen = 0
    digital_table_chunks_seen = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        for chunk, source_kind in _iter_table_chunks(chunks_path, digital_table_root):
            chunks_seen += 1
            table_json = _load_clause_detail_table_json(chunk)
            if table_json is None:
                continue
            table_chunks_seen += 1
            if source_kind == "digital_pdf":
                digital_table_chunks_seen += 1
            headers = table_json.get("headers") or []
            table_rows = table_json.get("rows") or []
            for row_index, raw_row in enumerate(table_rows):
                record = _build_record_from_chunk(chunk, row_index, raw_row, headers)
                if record is None:
                    continue
                output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                rows_written += 1
    return {
        "chunks_seen": chunks_seen,
        "table_chunks_seen": table_chunks_seen,
        "digital_table_chunks_seen": digital_table_chunks_seen,
        "rows_written": rows_written,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-mode", choices=INDEX_MODES, default="v2_only")
    parser.add_argument("--chunks-path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--digital-table-root",
        type=Path,
        default=config.DIGITAL_PDF_TABLES_DIR,
        help="디지털 생성 PDF table_json 산출물 루트.",
    )
    parser.add_argument("--no-digital-tables", action="store_true", help="별도 디지털 PDF table_json 산출물을 읽지 않습니다.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    chunks_path = args.chunks_path or resolve_clause_detail_source_chunks_path(args.index_mode)
    output_path = args.output or resolve_clause_detail_rows_path(args.index_mode)
    digital_table_root = None if args.no_digital_tables else args.digital_table_root
    if digital_table_root is not None and not digital_table_root.is_absolute():
        digital_table_root = ROOT / digital_table_root
    if not chunks_path.exists():
        raise SystemExit(f"chunks file not found: {chunks_path}")
    summary = build_clause_detail_rows(chunks_path, output_path, digital_table_root=digital_table_root)
    summary["output"] = str(output_path)
    summary["digital_table_root"] = str(digital_table_root) if digital_table_root is not None else None
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
