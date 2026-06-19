"""Dry-run planning for newly added project data files."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


EXCEL_SUFFIXES = {".xlsx", ".xls", ".csv"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
PDF_SUFFIXES = {".pdf"}


@dataclass(frozen=True)
class IntakePlan:
    path: str
    file_type: str
    steps: list[str]
    mutates_indexes: bool
    requires_practitioner_approval: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def plan_file_intake(path: str | Path) -> IntakePlan:
    """Return a non-mutating intake plan for a new source file."""

    source_path = Path(path)
    suffix = source_path.suffix.lower()
    if suffix in EXCEL_SUFFIXES:
        return _supported_plan(
            source_path,
            "excel",
            [
                "extract_rows",
                "stage_source_documents",
                "ontology_candidates_pending",
                "wait_for_practitioner_approval",
            ],
        )
    if suffix in PDF_SUFFIXES:
        return _supported_plan(
            source_path,
            "pdf",
            [
                "detect_pdf_text_layer",
                "choose_digital_or_scanned_pipeline",
                "stage_source_documents",
                "ontology_candidates_pending",
                "wait_for_practitioner_approval",
            ],
        )
    if suffix in IMAGE_SUFFIXES:
        return _supported_plan(
            source_path,
            "image",
            [
                "run_scanned_document_ocr",
                "stage_source_documents",
                "ontology_candidates_pending",
                "wait_for_practitioner_approval",
            ],
        )
    return IntakePlan(
        path=str(source_path),
        file_type="unsupported",
        steps=["reject_unsupported_file"],
        mutates_indexes=False,
        requires_practitioner_approval=False,
    )


def _supported_plan(path: Path, file_type: str, steps: list[str]) -> IntakePlan:
    return IntakePlan(
        path=str(path),
        file_type=file_type,
        steps=steps,
        mutates_indexes=False,
        requires_practitioner_approval=True,
    )
