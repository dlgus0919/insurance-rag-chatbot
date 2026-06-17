"""Validation helpers for hospital receipt OCR rows."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import re

from .models import DetailRow, ValidationIssue


def normalize_money(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("원", "").replace(",", "").replace(" ", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        return ""
    try:
        decimal = Decimal(text)
    except InvalidOperation:
        return ""
    if decimal == decimal.to_integral_value():
        return str(int(decimal))
    return format(decimal.normalize(), "f")


def normalize_quantity(value: str) -> str:
    text = str(value or "").strip().replace(",", "").replace("회", "").replace("일", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        return ""
    try:
        decimal = Decimal(text)
    except InvalidOperation:
        return ""
    if decimal == decimal.to_integral_value():
        return str(int(decimal))
    return format(decimal.normalize(), "f")


def validate_detail_row(row: DetailRow) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    row.unit_amount = normalize_money(row.unit_amount)
    row.count = normalize_quantity(row.count)
    row.days = normalize_quantity(row.days)
    row.total_amount = normalize_money(row.total_amount)
    row.insured_copay_amount = normalize_money(row.insured_copay_amount)
    row.insurer_paid_amount = normalize_money(row.insurer_paid_amount)
    row.full_self_pay_amount = normalize_money(row.full_self_pay_amount)
    row.nonpay_amount = normalize_money(row.nonpay_amount)
    row.normalized_code = normalize_code(row.raw_code)

    if not row.raw_name:
        issues.append(_issue(row, "error", "항목명이 비어 있습니다."))
    if not row.total_amount:
        issues.append(_issue(row, "error", "총액을 파싱할 수 없습니다."))
    if row.unit_amount and row.count and row.days and row.total_amount:
        expected = Decimal(row.unit_amount) * Decimal(row.count) * Decimal(row.days)
        actual = Decimal(row.total_amount)
        if expected != actual:
            issues.append(_issue(row, "warning", f"단가*횟수*일수({expected})와 총액({actual})이 일치하지 않습니다."))
    else:
        issues.append(_issue(row, "warning", "단가/횟수/일수/총액 중 일부가 비어 산식 검증이 불완전합니다."))

    components = [
        row.insured_copay_amount,
        row.insurer_paid_amount,
        row.full_self_pay_amount,
        row.nonpay_amount,
    ]
    if row.total_amount and any(component != "" for component in components):
        component_sum = sum(Decimal(component or "0") for component in components)
        if component_sum != Decimal(row.total_amount):
            issues.append(_issue(row, "warning", f"금액 구성 합계({component_sum})와 총액({row.total_amount})이 일치하지 않습니다."))

    if any(issue.severity == "error" for issue in issues):
        row.validation_status = "rejected"
    elif issues:
        row.validation_status = "review_required"
    else:
        row.validation_status = "verified"
    row.validation_reasons = [issue.reason for issue in issues]
    return issues


def normalize_code(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _issue(row: DetailRow, severity: str, reason: str) -> ValidationIssue:
    digest = hashlib.sha1(f"{row.row_id}:{reason}".encode("utf-8")).hexdigest()[:10]
    return ValidationIssue(
        issue_id=f"{row.row_id}_{digest}",
        severity=severity,  # type: ignore[arg-type]
        target_id=row.row_id,
        reason=reason,
        source_file=row.source_file,
        bbox=row.bbox,
    )
