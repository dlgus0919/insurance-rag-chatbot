"""Best-effort masking for OCR text before runtime artifacts are written."""

from __future__ import annotations

import re

from .models import OcrTable


REDACTION_PATTERNS = [
    (re.compile(r"\d{6}\s*-\s*\d{7}"), "[REDACTED_RRN]"),
    (re.compile(r"01[016789]\s*[-.)]?\s*\d{3,4}\s*[-.]?\s*\d{4}"), "[REDACTED_PHONE]"),
    (re.compile(r"0\d{1,2}\s*[-.)]?\s*\d{3,4}\s*[-.]?\s*\d{4}"), "[REDACTED_PHONE]"),
    (re.compile(r"\b\d{4}\s*[- ]\s*\d{4}\s*[- ]\s*\d{4}\s*[- ]\s*\d{4}\b"), "[REDACTED_CARD]"),
]


def redact_text(text: str) -> str:
    redacted = str(text or "")
    for pattern, replacement in REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_table(table: OcrTable) -> OcrTable:
    for cell in table.cells:
        cell.text = redact_text(cell.text)
        if "assigned_boxes" in cell.raw:
            for box in cell.raw["assigned_boxes"]:
                if isinstance(box, dict) and "text" in box:
                    box["text"] = redact_text(str(box["text"]))
        if "crop_boxes" in cell.raw:
            for box in cell.raw["crop_boxes"]:
                if isinstance(box, dict) and "text" in box:
                    box["text"] = redact_text(str(box["text"]))
    return table
