"""Runtime orchestration for hospital receipt OCR."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backends.opencv_paddle import PaddleOcrAdapter
from .backends.opencv_paddle import extract_tables_from_image as extract_opencv_tables
from .backends.opencv_paddle import save_cell_artifact
from .backends.ppstructure import PPStructureAdapter
from .backends.ppstructure import extract_tables_from_image as extract_ppstructure_tables
from .backends.surya import SuryaAdapter
from .backends.surya import extract_tables_from_image as extract_surya_tables
from .backends.tatr_ocr import TatrOcrAdapter
from .backends.tatr_ocr import extract_tables_from_image as extract_tatr_tables
from .claim_adapter import detail_rows_to_claim_items
from .models import ClaimManifest, HumanTask, SourceDocument, dataclass_to_dict
from .normalize import build_human_tasks, extract_receipt_summary, normalize_detail_rows
from .preprocess import (
    classify_document_from_text,
    collect_input_files,
    document_type_from_mode,
    load_rgb_image,
    make_source_document,
)
from .redaction import redact_table


def run_hospital_receipt_ocr(
    *,
    input_file: Path | None,
    input_dir: Path | None,
    output_dir: Path,
    strategy: str = "opencv_paddle",
    doc_type_mode: str = "auto",
    redact_sensitive: bool = True,
    no_llm: bool = True,
    export_claim_items: bool = False,
    fail_on_unverified: bool = False,
    allow_experimental_surya_inference: bool = False,
) -> dict[str, Any]:
    if strategy not in {"opencv_paddle", "ppstructure", "surya", "tatr_ocr"}:
        raise ValueError(f"지원하지 않는 strategy입니다: {strategy}")
    if not no_llm:
        raise ValueError("병원 영수증 OCR 지속 실행 경로에서는 LLM/VLM 호출을 지원하지 않습니다. --no-llm을 사용하세요.")

    output_dir.mkdir(parents=True, exist_ok=True)
    cell_dir = output_dir / "cell_artifacts"
    files = collect_input_files(input_file=input_file, input_dir=input_dir)
    backend = _make_backend(strategy, allow_experimental_surya_inference=allow_experimental_surya_inference)

    documents: list[SourceDocument] = []
    all_detail_rows = []
    all_receipt_summaries = []
    all_issues = []

    for page_index, path in enumerate(files):
        page_id = f"p{page_index + 1:03d}"
        image = load_rgb_image(path)
        tables = _extract_tables(strategy, image=image, page_id=page_id, backend=backend)
        page_text = "\n".join(cell.text for table in tables for cell in table.cells if cell.text)
        backend_text = getattr(backend, "last_page_text", "")
        classification_text = "\n".join(part for part in [backend_text, page_text] if part)
        if doc_type_mode == "auto":
            document_type, reason = classify_document_from_text(classification_text)
        else:
            document_type = document_type_from_mode(doc_type_mode)
            reason = f"forced:{doc_type_mode}"
        document = make_source_document(path, image, page_index, document_type, reason)
        documents.append(document)
        if document_type == "unknown":
            all_issues.append(
                {
                    "issue_id": f"{page_id}_unknown_document_type",
                    "severity": "warning",
                    "target_id": page_id,
                    "reason": "문서 유형을 자동 분류하지 못했습니다.",
                    "source_file": path.name,
                    "bbox": None,
                }
            )

        if not tables:
            all_issues.append(
                {
                    "issue_id": f"{page_id}_no_table",
                    "severity": "error",
                    "target_id": page_id,
                    "reason": f"{strategy} backend에서 table을 검출하지 못했습니다.",
                    "source_file": path.name,
                    "bbox": None,
                }
            )
            continue

        for table in tables:
            if redact_sensitive:
                table = redact_table(table)
            save_cell_artifact(cell_dir / f"{page_id}_{table.table_id}.json", table)
            if document_type == "medical_detail_statement":
                rows, issues = normalize_detail_rows(table, source_file=path.name, page_label=str(page_index + 1))
                all_detail_rows.extend(rows)
                all_issues.extend(issues)
            elif document_type == "medical_bill_receipt":
                all_receipt_summaries.append(extract_receipt_summary(table, source_file=path.name, page_label=str(page_index + 1)))

    backend_unavailable_reason = getattr(backend, "unavailable_reason", "")
    if backend_unavailable_reason:
        all_issues.append(
            {
                "issue_id": f"{strategy}_backend_unavailable",
                "severity": "error",
                "target_id": strategy,
                "reason": f"{strategy} backend unavailable: {backend_unavailable_reason}",
                "source_file": "",
                "bbox": None,
            }
        )
    human_tasks = build_human_tasks(all_detail_rows, [issue for issue in all_issues if not isinstance(issue, dict)])
    if backend_unavailable_reason:
        human_tasks.append(
            HumanTask(
                task_id=f"task_{strategy}_backend_unavailable",
                target_id=strategy,
                reason=f"{strategy} backend를 사용할 수 없어 문서 유형 분류와 row 승격을 완료하지 못했습니다.",
                source_file="",
            )
        )
    dict_issues = [dataclass_to_dict(issue) if not isinstance(issue, dict) else issue for issue in all_issues]
    claim_items_ready = detail_rows_to_claim_items(all_detail_rows) if export_claim_items else []

    manifest = ClaimManifest(
        schema_version="hospital_receipt_claim_manifest.v1",
        claim_document_id=output_dir.name,
        source_documents=[dataclass_to_dict(document) for document in documents],
        detail_rows=[dataclass_to_dict(row) for row in all_detail_rows],
        receipt_summary=_merge_receipt_summaries(all_receipt_summaries),
        validations=dict_issues,
        claim_items_ready=claim_items_ready,
        human_tasks=[dataclass_to_dict(task) for task in human_tasks],
    )

    _write_jsonl(output_dir / "documents.jsonl", [dataclass_to_dict(document) for document in documents])
    _write_jsonl(output_dir / "detail_rows.jsonl", [dataclass_to_dict(row) for row in all_detail_rows])
    _write_json(output_dir / "receipt_summary.json", manifest.receipt_summary)
    _write_json(output_dir / "validation_report.json", {"issues": dict_issues})
    _write_json(output_dir / "claim_manifest.json", dataclass_to_dict(manifest))
    _write_json(output_dir / "claim_items_ready.json", claim_items_ready)
    _write_jsonl(output_dir / "human_tasks.jsonl", [dataclass_to_dict(task) for task in human_tasks])

    summary = {
        "schema_version": "hospital_receipt_ocr_run.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy,
        "input_count": len(files),
        "processed_documents": len(documents),
        "document_type_counts": _counts(document.document_type for document in documents),
        "detail_row_count": len(all_detail_rows),
        "verified_detail_row_count": sum(1 for row in all_detail_rows if row.validation_status == "verified"),
        "claim_items_ready_count": len(claim_items_ready),
        "validation_issue_count": len(dict_issues),
        "human_task_count": len(human_tasks),
        "redact_sensitive": redact_sensitive,
        "llm_used": False,
        "ocr_degraded": bool(backend_unavailable_reason),
        "ocr_unavailable_reason": backend_unavailable_reason,
    }
    _write_json(output_dir / "run_summary.json", summary)
    if fail_on_unverified and (summary["validation_issue_count"] or summary["human_task_count"]):
        raise RuntimeError("검증 실패 또는 human task가 있어 --fail-on-unverified 조건을 충족하지 못했습니다.")
    return summary


def _make_backend(strategy: str, *, allow_experimental_surya_inference: bool) -> Any:
    if strategy == "opencv_paddle":
        return PaddleOcrAdapter()
    if strategy == "ppstructure":
        return PPStructureAdapter()
    if strategy == "surya":
        return SuryaAdapter(allow_inference=allow_experimental_surya_inference)
    if strategy == "tatr_ocr":
        return TatrOcrAdapter()
    raise ValueError(f"지원하지 않는 strategy입니다: {strategy}")


def _extract_tables(strategy: str, *, image, page_id: str, backend: Any):  # noqa: ANN001
    if strategy == "opencv_paddle":
        return extract_opencv_tables(image, page_id=page_id, ocr=backend)
    if strategy == "ppstructure":
        return extract_ppstructure_tables(image, page_id=page_id, ppstructure=backend)
    if strategy == "surya":
        return extract_surya_tables(image, page_id=page_id, surya=backend)
    if strategy == "tatr_ocr":
        return extract_tatr_tables(image, page_id=page_id, tatr=backend)
    raise ValueError(f"지원하지 않는 strategy입니다: {strategy}")


def _merge_receipt_summaries(summaries) -> dict[str, Any]:  # noqa: ANN001
    if not summaries:
        return {}
    return {
        "summaries": [dataclass_to_dict(summary) for summary in summaries],
        "number_candidates": [number for summary in summaries for number in summary.numbers],
    }


def _counts(values) -> dict[str, int]:  # noqa: ANN001
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
