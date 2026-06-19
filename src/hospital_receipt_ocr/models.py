"""Data contracts for hospital receipt OCR runtime outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


DocumentType = Literal[
    "medical_detail_statement",
    "medical_bill_receipt",
    "diagnosis_certificate",
    "surgery_certificate",
    "unknown",
]

ValidationStatus = Literal["verified", "review_required", "rejected"]


@dataclass
class SourceDocument:
    document_id: str
    source_file: str
    page_index: int
    width: int
    height: int
    document_type: DocumentType = "unknown"
    classification_reason: str = ""
    status: str = "processed"
    errors: list[str] = field(default_factory=list)


@dataclass
class OcrCell:
    cell_id: str
    page_id: str
    row: int
    col: int
    bbox: list[int]
    text: str = ""
    confidence: float | None = None
    source_method: str = "opencv_paddle"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OcrTable:
    table_id: str
    page_id: str
    bbox: list[int]
    rows: int
    cols: int
    cells: list[OcrCell] = field(default_factory=list)


@dataclass
class DetailRow:
    source_type: DocumentType
    source_file: str
    page_label: str
    row_id: str
    bbox: list[int] | None
    item_group: str = ""
    service_date: str = ""
    raw_code: str = ""
    normalized_code: str = ""
    raw_name: str = ""
    unit_amount: str = ""
    count: str = ""
    days: str = ""
    total_amount: str = ""
    insured_copay_amount: str = ""
    insurer_paid_amount: str = ""
    full_self_pay_amount: str = ""
    nonpay_amount: str = ""
    validation_status: ValidationStatus = "review_required"
    validation_reasons: list[str] = field(default_factory=list)
    source_cells: list[str] = field(default_factory=list)


@dataclass
class ReceiptSummary:
    source_file: str
    page_label: str
    document_type: DocumentType = "medical_bill_receipt"
    numbers: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    validation_status: ValidationStatus = "review_required"
    validation_reasons: list[str] = field(default_factory=list)


@dataclass
class ValidationIssue:
    issue_id: str
    severity: Literal["info", "warning", "error"]
    target_id: str
    reason: str
    source_file: str = ""
    bbox: list[int] | None = None


@dataclass
class HumanTask:
    task_id: str
    target_id: str
    reason: str
    source_file: str
    page_label: str = ""
    bbox: list[int] | None = None


@dataclass
class ClaimManifest:
    schema_version: str
    claim_document_id: str
    source_documents: list[dict[str, Any]] = field(default_factory=list)
    case_context_candidates: dict[str, Any] = field(default_factory=dict)
    detail_rows: list[dict[str, Any]] = field(default_factory=list)
    receipt_summary: dict[str, Any] = field(default_factory=dict)
    diagnosis_fields: dict[str, Any] = field(default_factory=dict)
    surgery_fields: dict[str, Any] = field(default_factory=dict)
    validations: list[dict[str, Any]] = field(default_factory=list)
    claim_items_ready: list[dict[str, Any]] = field(default_factory=list)
    human_tasks: list[dict[str, Any]] = field(default_factory=list)


def dataclass_to_dict(value: Any) -> dict[str, Any]:
    data = asdict(value)
    return _stringify_paths(data)


def _stringify_paths(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _stringify_paths(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_paths(v) for v in value]
    return value
