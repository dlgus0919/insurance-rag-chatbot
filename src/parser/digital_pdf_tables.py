"""Digital-born PDF table extraction utilities.

This module only extracts source-grounded table structure from a PDF text layer
and page drawing geometry. It does not create insurance decisions or product
knowledge; downstream code must keep using the extracted source rows as
evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from src.parser.chunker import Chunk, _extract_codes

try:  # pragma: no cover - import availability is environment dependent
    from src.config import PdfSource
except Exception:  # pragma: no cover
    PdfSource = Any  # type: ignore


DIGITAL_TABLE_SCHEMA_VERSION = 1
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class DigitalPdfTableSummary:
    """Summary of a digital PDF table extraction run."""

    source_pdf: str
    doc_short: str
    pages_seen: int
    tables_seen: int
    table_chunks: int


def normalize_table_cell(value: Any) -> str:
    """Normalize a PDF table cell while preserving source wording."""

    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def _trim_empty_edges(matrix: list[list[str]]) -> list[list[str]]:
    rows = [[normalize_table_cell(cell) for cell in row] for row in matrix]
    rows = [row for row in rows if any(row)]
    if not rows:
        return []

    max_cols = max(len(row) for row in rows)
    padded = [row + [""] * (max_cols - len(row)) for row in rows]
    non_empty_cols = [
        index
        for index in range(max_cols)
        if any(row[index] for row in padded)
    ]
    if not non_empty_cols:
        return []
    first_col, last_col = non_empty_cols[0], non_empty_cols[-1]
    return [row[first_col : last_col + 1] for row in padded]


def _looks_like_header(row: list[str], body_rows: list[list[str]]) -> bool:
    non_empty = [cell for cell in row if cell]
    if len(non_empty) < 2 or not body_rows:
        return False
    if any(len(cell) > 32 for cell in non_empty):
        return False
    if any(("." in cell and len(cell) > 12) for cell in non_empty):
        return False
    body_has_longer_text = any(len(cell) > 32 for body in body_rows for cell in body if cell)
    return body_has_longer_text or any(cell in {"구분", "항목", "보상금액", "공제금액"} for cell in non_empty)


def _unique_headers(headers: Iterable[str], column_count: int) -> list[str]:
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(headers):
        name = normalize_table_cell(raw) or f"열{index + 1}"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        result.append(name)
    while len(result) < column_count:
        result.append(f"열{len(result) + 1}")
    return result[:column_count]


def table_matrix_to_json(matrix: list[list[Any]]) -> dict[str, Any] | None:
    """Convert a raw extracted table matrix to the project table_json shape."""

    normalized = _trim_empty_edges([[normalize_table_cell(cell) for cell in row] for row in matrix])
    if len(normalized) < 2:
        return None

    column_count = max(len(row) for row in normalized)
    rows = [row + [""] * (column_count - len(row)) for row in normalized]
    first_row, body_rows = rows[0], rows[1:]
    if _looks_like_header(first_row, body_rows):
        headers = _unique_headers(first_row, column_count)
        data_rows = body_rows
    else:
        headers = [f"열{index + 1}" for index in range(column_count)]
        data_rows = rows

    payload_rows: list[dict[str, str]] = []
    for row in data_rows:
        row_payload = {
            header: normalize_table_cell(row[index]) if index < len(row) else ""
            for index, header in enumerate(headers)
        }
        if any(row_payload.values()):
            payload_rows.append(row_payload)

    if not payload_rows:
        return None

    text_size = sum(len(value) for row in payload_rows for value in row.values())
    if text_size < 8:
        return None

    return {
        "schema_version": DIGITAL_TABLE_SCHEMA_VERSION,
        "headers": headers,
        "rows": payload_rows,
    }


def table_json_to_text(table_json: dict[str, Any]) -> str:
    """Render table_json into deterministic text for retrieval."""

    headers = [normalize_table_cell(header) for header in table_json.get("headers", [])]
    lines = [" | ".join(header for header in headers if header)]
    for row in table_json.get("rows", []):
        if isinstance(row, dict):
            values = [normalize_table_cell(row.get(header, "")) for header in headers]
        else:
            values = [normalize_table_cell(value) for value in row]
        line = " | ".join(value for value in values if value)
        if line:
            lines.append(line)
    return "\n".join(line for line in lines if line).strip()


def _metadata_from_source(doc_source: PdfSource, page_no: int, table_index: int, bbox: Any, table_json: dict[str, Any]) -> dict[str, Any]:
    text = table_json_to_text(table_json)
    metadata: dict[str, Any] = {
        "canonical_chunk_id": "",
        "source_chunk_id": "",
        "page_start": page_no,
        "page_end": page_no,
        "volume": None,
        "part": None,
        "chapter": None,
        "section": "",
        "codes": _extract_codes(text),
        "is_code_table": len(_extract_codes(text)) >= 5,
        "char_count": len(text),
        "doc_short": doc_source.doc_short,
        "doc_name": doc_source.doc_name,
        "doc_type": doc_source.doc_type,
        "pdf_filename": doc_source.path.name,
        "content_type": "table",
        "source_method": "digital_pdf_table",
        "table_json": json.dumps(table_json, ensure_ascii=False),
        "digital_table_schema_version": DIGITAL_TABLE_SCHEMA_VERSION,
        "digital_table_index": table_index,
        "bbox": list(bbox) if bbox else None,
    }
    for field in (
        "insurance_company",
        "is_own_company",
        "product_name",
        "product_type",
        "effective_date",
        "version",
    ):
        value = getattr(doc_source, field, None)
        if value is not None:
            metadata[field] = value
    return metadata


def extract_digital_pdf_table_chunks(
    doc_source: PdfSource,
    *,
    id_offset: int = 0,
    min_rows: int = 2,
) -> tuple[list[Chunk], DigitalPdfTableSummary]:
    """Extract digital PDF tables as project chunks.

    The extractor uses pdfplumber because it operates on text-layer coordinates
    and vector geometry, avoiding OCR or external LLM calls.
    """

    if not doc_source.path.exists():
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {doc_source.path}")
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency availability
        raise RuntimeError("pdfplumber가 설치되어 있지 않아 디지털 PDF 표를 추출할 수 없습니다.") from exc

    chunks: list[Chunk] = []
    tables_seen = 0
    with pdfplumber.open(str(doc_source.path)) as pdf:
        pages_seen = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, start=1):
            try:
                tables = page.find_tables()
            except Exception as exc:  # pragma: no cover - corrupt page guard
                print(f"[digital-pdf-table] {doc_source.doc_short} p.{page_no} 표 탐지 실패: {exc}")
                continue
            for table_index, table in enumerate(tables, start=1):
                tables_seen += 1
                try:
                    matrix = table.extract() or []
                except Exception as exc:  # pragma: no cover - corrupt table guard
                    print(f"[digital-pdf-table] {doc_source.doc_short} p.{page_no} t{table_index} 추출 실패: {exc}")
                    continue
                if len(matrix) < min_rows:
                    continue
                table_json = table_matrix_to_json(matrix)
                if table_json is None:
                    continue
                text = table_json_to_text(table_json)
                if not text:
                    continue
                chunk_id = f"{doc_source.doc_short}_tbl_{id_offset + len(chunks):06d}"
                metadata = _metadata_from_source(doc_source, page_no, table_index, getattr(table, "bbox", None), table_json)
                metadata["canonical_chunk_id"] = chunk_id
                metadata["source_chunk_id"] = chunk_id
                chunks.append(Chunk(id=chunk_id, text=text, metadata=metadata))
    return chunks, DigitalPdfTableSummary(
        source_pdf=str(doc_source.path),
        doc_short=doc_source.doc_short,
        pages_seen=pages_seen,
        tables_seen=tables_seen,
        table_chunks=len(chunks),
    )


def write_digital_pdf_table_artifacts(chunks: list[Chunk], output_root: Path, doc_short: str) -> Path:
    """Write extracted digital PDF table chunks under data/extracted_digital_pdf."""

    doc_root = output_root / doc_short
    tables_root = doc_root / "tables"
    tables_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": DIGITAL_TABLE_SCHEMA_VERSION,
        "doc_short": doc_short,
        "table_count": len(chunks),
        "chunks": [],
    }
    for index, chunk in enumerate(chunks, start=1):
        page = int(chunk.metadata.get("page_start") or 0)
        table_name = f"p{page:03d}_t{index:03d}"
        table_json = json.loads(str(chunk.metadata.get("table_json") or "{}"))
        json_path = tables_root / f"{table_name}.json"
        text_path = tables_root / f"{table_name}.txt"
        json_path.write_text(json.dumps(table_json, ensure_ascii=False, indent=2), encoding="utf-8")
        text_path.write_text(chunk.text, encoding="utf-8")
        manifest["chunks"].append(
            {
                **asdict(chunk),
                "artifact_json": str(json_path.relative_to(doc_root)),
                "artifact_text": str(text_path.relative_to(doc_root)),
            }
        )
    manifest_path = doc_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def load_digital_pdf_table_chunks(extracted_root: Path) -> list[Chunk]:
    """Load digital PDF table chunks previously written by this module."""

    chunks: list[Chunk] = []
    if not extracted_root.exists():
        return chunks
    for manifest_path in sorted(extracted_root.glob("*/manifest.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for raw_chunk in payload.get("chunks") or []:
            if not isinstance(raw_chunk, dict):
                continue
            chunk_id = str(raw_chunk.get("id") or "").strip()
            text = str(raw_chunk.get("text") or "").strip()
            metadata = raw_chunk.get("metadata")
            if chunk_id and text and isinstance(metadata, dict):
                chunks.append(Chunk(id=chunk_id, text=text, metadata=metadata))
    return chunks
