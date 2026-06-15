"""Clause detail row manifest loading utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from src import config


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ClauseDetailRowRecord:
    """A source-grounded row extracted from OCR table_json."""

    row_id: str
    doc_short: str
    article: str
    table_label: str
    page: int | None
    chunk_id: str
    parent_heading: str
    row_label: str
    value_text: str
    numbers: list[str]
    source_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClauseDetailRowRecord | None":
        if not isinstance(payload, dict):
            return None
        try:
            row_id = str(payload.get("row_id") or "").strip()
            doc_short = str(payload.get("doc_short") or "").strip()
            chunk_id = str(payload.get("chunk_id") or "").strip()
            value_text = str(payload.get("value_text") or "").strip()
        except Exception:
            return None
        if not row_id or not doc_short or not chunk_id or not value_text:
            return None
        raw_numbers = payload.get("numbers") or []
        numbers = [str(value).strip() for value in raw_numbers if str(value).strip()] if isinstance(raw_numbers, list) else []
        raw_page = payload.get("page")
        try:
            page = int(raw_page) if raw_page is not None else None
        except (TypeError, ValueError):
            page = None
        source_metadata = payload.get("source_metadata")
        return cls(
            row_id=row_id,
            doc_short=doc_short,
            article=str(payload.get("article") or "").strip(),
            table_label=str(payload.get("table_label") or "").strip(),
            page=page,
            chunk_id=chunk_id,
            parent_heading=str(payload.get("parent_heading") or "").strip(),
            row_label=str(payload.get("row_label") or "").strip(),
            value_text=value_text,
            numbers=numbers,
            source_metadata=source_metadata if isinstance(source_metadata, dict) else {},
        )

    @property
    def search_text(self) -> str:
        return " ".join(
            part
            for part in (
                self.article,
                self.table_label,
                self.parent_heading,
                self.row_label,
                self.value_text,
            )
            if part
        )


def resolve_clause_detail_rows_path(index_mode: str) -> Path:
    normalized = (index_mode or "v2_only").strip().lower()
    if normalized == "v2_only":
        return config.ROOT_DIR / "data" / "index_v2_manual" / "clause_detail_rows.jsonl"
    if normalized == "v1_v2_combined":
        return config.ROOT_DIR / "data" / "index_v1_v2_combined" / "clause_detail_rows.jsonl"
    return config.ROOT_DIR / "data" / "index" / "clause_detail_rows.jsonl"


def resolve_clause_detail_source_chunks_path(index_mode: str) -> Path:
    normalized = (index_mode or "v2_only").strip().lower()
    if normalized == "v2_only":
        return config.ROOT_DIR / "data" / "processed" / "chunks_v2_manual.jsonl"
    if normalized == "v1_v2_combined":
        return config.ROOT_DIR / "data" / "processed" / "chunks_v1_v2_combined.jsonl"
    return config.CHUNKS_PATH


@lru_cache(maxsize=8)
def load_clause_detail_row_records(path_value: str) -> tuple[ClauseDetailRowRecord, ...]:
    path = Path(path_value)
    if not path.exists():
        return ()
    records: list[ClauseDetailRowRecord] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                payload = json.loads(line)
                record = ClauseDetailRowRecord.from_payload(payload)
                if record is not None:
                    records.append(record)
    except (OSError, json.JSONDecodeError):
        return ()
    return tuple(records)


class ClauseDetailRowStore:
    """Lazy loader for a clause_detail_rows JSONL manifest."""

    def __init__(self, path: Path | str | None):
        self.path = Path(path) if path else None

    def is_available(self) -> bool:
        return bool(self.path and self.path.exists())

    def records(self) -> tuple[ClauseDetailRowRecord, ...]:
        if not self.path:
            return ()
        return load_clause_detail_row_records(str(self.path))
