"""Heuristics to suppress OCR table false positives."""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_HEADER_RE = re.compile(r"^col_\d+$", re.IGNORECASE)
_SENTENCE_END_RE = re.compile(r"(다\.?|니다\.?|한다\.?|하였다\.?)$")
_KNOWN_STRUCTURED_HEADERS = (
    "수술명",
    "수술해설",
    "수술종수",
    "1-3종",
    "1-5종",
    "신1-5종",
    "장해",
    "지급률",
    "분류",
    "코드",
)


def _normalize_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_placeholder_header(value: str) -> bool:
    return not value or _PLACEHOLDER_HEADER_RE.match(value) is not None


def _looks_structured_header(value: str) -> bool:
    return any(token in value for token in _KNOWN_STRUCTURED_HEADERS)


def _row_to_values(row: Any, headers: list[str]) -> list[str]:
    if isinstance(row, dict):
        return [str(row.get(header, "")).strip() for header in headers]
    if isinstance(row, list):
        padded = [str(value).strip() for value in row] + [""] * max(0, len(headers) - len(row))
        return padded[: len(headers)]
    return []


def _single_column_prose_like(header: str, rows: list[Any]) -> bool:
    values = []
    for row in rows:
        row_values = _row_to_values(row, [header])
        if not row_values:
            continue
        value = row_values[0].strip()
        if value:
            values.append(value)

    if len(values) < 2:
        return False

    long_count = sum(1 for value in values if len(value) >= 24)
    sentence_like_count = sum(1 for value in values if _SENTENCE_END_RE.search(value) or len(value.split()) >= 7)
    ratio = long_count / max(1, len(values))
    return ratio >= 0.6 and sentence_like_count >= 1 and not _looks_structured_header(header)


def evaluate_table_quality(table_json: dict | None) -> tuple[bool, str | None]:
    """Return (should_downcast, reason) for OCR table JSON."""

    if not isinstance(table_json, dict):
        return True, "invalid_table_json"

    headers_raw = table_json.get("headers", [])
    headers = [_normalize_header(value) for value in headers_raw]
    rows = table_json.get("rows", [])

    if not headers or all(_is_placeholder_header(header) for header in headers):
        return True, "missing_headers"
    if not isinstance(rows, list) or len(rows) == 0:
        return True, "rows_empty"

    expected_keys = set(headers)
    mismatch_count = 0
    non_empty_rows = 0
    for row in rows:
        if isinstance(row, dict):
            row_keys = {_normalize_header(key) for key in row.keys()}
            if row_keys and row_keys != expected_keys:
                mismatch_count += 1
            if any(str(value).strip() for value in row.values()):
                non_empty_rows += 1
        elif isinstance(row, list):
            if any(str(value).strip() for value in row):
                non_empty_rows += 1
        else:
            mismatch_count += 1

    if non_empty_rows == 0:
        return True, "rows_effectively_empty"
    if mismatch_count / max(1, len(rows)) >= 0.5:
        return True, "row_header_mismatch"

    if len(headers) == 1 and _single_column_prose_like(headers[0], rows):
        return True, "single_column_prose_like"

    return False, None

