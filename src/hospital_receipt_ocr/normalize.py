"""Normalize OCR tables into hospital receipt domain records."""

from __future__ import annotations

from dataclasses import replace
import re

from .models import DetailRow, HumanTask, OcrTable, ReceiptSummary, ValidationIssue
from .validation import validate_detail_row


DETAIL_HEADERS = ("항목", "일자", "코드", "명칭", "금액", "횟수", "일수", "총액")


def normalize_detail_rows(table: OcrTable, *, source_file: str, page_label: str) -> tuple[list[DetailRow], list[ValidationIssue]]:
    rows_by_index: dict[int, list] = {}
    for cell in table.cells:
        rows_by_index.setdefault(cell.row, []).append(cell)

    detail_rows: list[DetailRow] = []
    issues: list[ValidationIssue] = []
    header_row = _find_header_row(rows_by_index)
    for row_index in sorted(rows_by_index):
        if row_index <= header_row:
            continue
        cells = sorted(rows_by_index[row_index], key=lambda c: c.col)
        if not any(cell.text.strip() for cell in cells):
            continue
        if len(cells) < 8:
            continue
        row = _row_from_cells(
            cells,
            row_id=f"{table.page_id}_detail_r{row_index:03d}",
            source_file=source_file,
            page_label=page_label,
            bbox=_merge_bbox([cell.bbox for cell in cells]),
        )
        row_issues = validate_detail_row(row)
        detail_rows.append(row)
        issues.extend(row_issues)
    return detail_rows, issues


def extract_receipt_summary(table: OcrTable, *, source_file: str, page_label: str) -> ReceiptSummary:
    text = "\n".join(cell.text for cell in table.cells if cell.text)
    numbers = re.findall(r"\d{1,3}(?:,\d{3})+|\d{4,}", text)
    summary = ReceiptSummary(source_file=source_file, page_label=page_label, numbers=numbers)
    if not numbers:
        summary.validation_reasons.append("영수증 숫자 후보를 찾지 못했습니다.")
    else:
        summary.fields["number_candidates"] = ", ".join(numbers)
    return summary


def build_human_tasks(detail_rows: list[DetailRow], issues: list[ValidationIssue]) -> list[HumanTask]:
    tasks: list[HumanTask] = []
    for row in detail_rows:
        if row.validation_status == "verified":
            continue
        reason = "; ".join(row.validation_reasons) if row.validation_reasons else "검증이 완료되지 않았습니다."
        tasks.append(
            HumanTask(
                task_id=f"task_{row.row_id}",
                target_id=row.row_id,
                reason=reason,
                source_file=row.source_file,
                page_label=row.page_label,
                bbox=row.bbox,
            )
        )
    issue_targets = {task.target_id for task in tasks}
    for issue in issues:
        if issue.target_id in issue_targets:
            continue
        tasks.append(
            HumanTask(
                task_id=f"task_{issue.issue_id}",
                target_id=issue.target_id,
                reason=issue.reason,
                source_file=issue.source_file,
                bbox=issue.bbox,
            )
        )
    return tasks


def _find_header_row(rows_by_index: dict[int, list]) -> int:
    for row_index in sorted(rows_by_index):
        row_text = "".join(cell.text for cell in rows_by_index[row_index])
        compact = re.sub(r"\s+", "", row_text)
        if sum(1 for header in DETAIL_HEADERS if header in compact) >= 3:
            return row_index
    first_detail_row = _infer_first_detail_row(rows_by_index)
    if first_detail_row is not None:
        return first_detail_row - 1
    return -1


def _infer_first_detail_row(rows_by_index: dict[int, list]) -> int | None:
    for row_index in sorted(rows_by_index):
        texts = [cell.text.strip() for cell in rows_by_index[row_index] if cell.text.strip()]
        if len(texts) < 5:
            continue
        row_text = " ".join(texts)
        has_date = bool(re.search(r"20\d{6}", row_text))
        amount_like_count = sum(1 for text in texts if re.fullmatch(r"[\d,]{2,}", text.replace(" ", "")))
        has_code_like = any(re.search(r"[A-Z가-힣]?\d{3,}", text.replace(" ", "")) for text in texts)
        if has_date and amount_like_count >= 2 and has_code_like:
            return row_index
    return None


def _row_from_cells(
    cells: list,
    *,
    row_id: str,
    source_file: str,
    page_label: str,
    bbox: list[int],
) -> DetailRow:
    normalized_cells = _normalize_row_columns(cells)
    name_col = _find_name_col(normalized_cells)
    fields = _extract_fields_by_anchor(normalized_cells, name_col)
    return DetailRow(
        source_type="medical_detail_statement",
        source_file=source_file,
        page_label=page_label,
        row_id=row_id,
        bbox=bbox,
        item_group=fields["item_group"],
        service_date=fields["service_date"],
        raw_code=fields["raw_code"],
        raw_name=fields["raw_name"],
        unit_amount=fields["unit_amount"],
        count=fields["count"],
        days=fields["days"],
        total_amount=fields["total_amount"],
        insured_copay_amount=fields["insured_copay_amount"],
        insurer_paid_amount=fields["insurer_paid_amount"],
        full_self_pay_amount=fields["full_self_pay_amount"],
        nonpay_amount=fields["nonpay_amount"],
        source_cells=[cell.cell_id for cell in cells],
    )


def _normalize_row_columns(cells: list) -> list:
    return sorted(
        (replace(cell, text=(cell.text or "").strip()) for cell in cells),
        key=lambda cell: cell.col,
    )


def _find_name_col(cells: list) -> int | None:
    scored: list[tuple[int, int, int]] = []
    for cell in cells:
        text = cell.text
        if not text:
            continue
        compact = re.sub(r"\s+", "", text)
        if _looks_numeric(compact) or _looks_service_date(compact):
            continue
        width = max(0, cell.bbox[2] - cell.bbox[0])
        has_letters = bool(re.search(r"[가-힣A-Za-z]", compact))
        if not has_letters:
            continue
        code_penalty = 300 if _looks_code_like(compact) and len(compact) <= 12 else 0
        score = width + len(compact) * 8 - code_penalty
        scored.append((score, cell.col, len(compact)))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def _extract_fields_by_anchor(cells: list, name_col: int | None) -> dict[str, str]:
    by_col = {cell.col: cell.text for cell in cells}
    nonempty_left = [cell for cell in cells if cell.text and (name_col is None or cell.col < name_col)]
    if name_col is None:
        return _extract_fields_by_position(cells)

    raw_name = by_col.get(name_col, "")
    service_date = ""
    raw_code = ""
    item_group = ""
    for cell in nonempty_left:
        compact = re.sub(r"\s+", "", cell.text)
        if not service_date and _looks_service_date(compact):
            service_date = cell.text
        elif _looks_code_like(compact):
            raw_code = cell.text
        elif not item_group:
            item_group = cell.text

    unit_col = _first_money_col_after(cells, name_col)
    if unit_col is None:
        unit_col = name_col + 1

    return {
        "item_group": item_group,
        "service_date": service_date,
        "raw_code": raw_code,
        "raw_name": raw_name,
        "unit_amount": by_col.get(unit_col, ""),
        "count": by_col.get(unit_col + 1, ""),
        "days": by_col.get(unit_col + 2, ""),
        "total_amount": by_col.get(unit_col + 3, ""),
        "insured_copay_amount": by_col.get(unit_col + 4, ""),
        "insurer_paid_amount": by_col.get(unit_col + 5, ""),
        "full_self_pay_amount": by_col.get(unit_col + 6, ""),
        "nonpay_amount": by_col.get(unit_col + 7, ""),
    }


def _extract_fields_by_position(cells: list) -> dict[str, str]:
    texts = [cell.text for cell in cells]
    padded = texts + [""] * max(0, 12 - len(texts))
    return {
        "item_group": padded[0],
        "service_date": padded[1],
        "raw_code": padded[2],
        "raw_name": padded[3],
        "unit_amount": padded[4],
        "count": padded[5],
        "days": padded[6],
        "total_amount": padded[7],
        "insured_copay_amount": padded[8],
        "insurer_paid_amount": padded[9],
        "full_self_pay_amount": padded[10],
        "nonpay_amount": padded[11],
    }


def _first_money_col_after(cells: list, name_col: int) -> int | None:
    for cell in cells:
        if cell.col <= name_col or not cell.text:
            continue
        if cell.col - name_col > 2:
            return None
        if _looks_money_like(cell.text):
            return cell.col
    return None


def _looks_money_like(value: str) -> bool:
    compact = re.sub(r"[^0-9]", "", value or "")
    return len(compact) >= 2


def _looks_numeric(value: str) -> bool:
    compact = re.sub(r"[^0-9.]", "", value or "")
    return bool(compact) and len(compact) >= max(1, len(value) - 2)


def _looks_service_date(value: str) -> bool:
    return bool(re.search(r"20\d{4,6}", value)) or "~" in value or "-" in value


def _looks_code_like(value: str) -> bool:
    compact = re.sub(r"\s+", "", value or "")
    has_digit = bool(re.search(r"\d", compact))
    if not has_digit:
        return False
    if not re.fullmatch(r"[\[\]A-Za-z가-힣0-9./\\-]+", compact):
        return False
    digit_count = sum(1 for char in compact if char.isdigit())
    hangul_count = len(re.findall(r"[가-힣]", compact))
    starts_like_code = bool(re.match(r"[\[A-Z]|\d", compact))
    return starts_like_code and (digit_count >= 3 or (digit_count >= 1 and hangul_count <= 2))


def _merge_bbox(bboxes: list[list[int]]) -> list[int]:
    return [
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    ]
