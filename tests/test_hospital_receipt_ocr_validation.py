from __future__ import annotations

from src.hospital_receipt_ocr.claim_adapter import detail_rows_to_claim_items
from src.hospital_receipt_ocr.models import DetailRow, OcrCell, OcrTable
from src.hospital_receipt_ocr.normalize import normalize_detail_rows
from src.hospital_receipt_ocr.preprocess import classify_document_from_text
from src.hospital_receipt_ocr.redaction import redact_text
from src.hospital_receipt_ocr.validation import normalize_money, normalize_quantity, validate_detail_row


def test_normalize_money_and_quantity() -> None:
    assert normalize_money("1,034,770원") == "1034770"
    assert normalize_quantity("0.50") == "0.5"


def test_detail_row_validation_and_claim_adapter_quantity_one() -> None:
    row = DetailRow(
        source_type="medical_detail_statement",
        source_file="sample.jpg",
        page_label="1",
        row_id="detail_001",
        bbox=[0, 0, 100, 20],
        item_group="마취료",
        raw_code="L1213",
        raw_name="척추마취관리기본",
        unit_amount="117,170",
        count="1",
        days="1",
        total_amount="117,170",
        insured_copay_amount="23,434",
        insurer_paid_amount="93,736",
        full_self_pay_amount="0",
        nonpay_amount="0",
    )

    issues = validate_detail_row(row)
    items = detail_rows_to_claim_items([row])

    assert issues == []
    assert row.validation_status == "verified"
    assert row.normalized_code == "L1213"
    assert items[0]["claimed_amount"] == "117170"
    assert items[0]["insured_copay_amount"] == "23434"
    assert items[0]["quantity"] == "1"


def test_invalid_row_is_not_promoted_to_claim_items() -> None:
    row = DetailRow(
        source_type="medical_detail_statement",
        source_file="sample.jpg",
        page_label="1",
        row_id="detail_bad",
        bbox=[0, 0, 100, 20],
        raw_name="",
        unit_amount="100",
        count="2",
        days="1",
        total_amount="999",
    )

    issues = validate_detail_row(row)

    assert issues
    assert row.validation_status == "rejected"
    assert detail_rows_to_claim_items([row]) == []


def test_redact_text_masks_common_sensitive_identifiers() -> None:
    text = "주민등록번호 900101-1234567 전화 010-1234-5678 카드 1234-5678-1234-5678"

    redacted = redact_text(text)

    assert "900101-1234567" not in redacted
    assert "010-1234-5678" not in redacted
    assert "1234-5678-1234-5678" not in redacted
    assert "[REDACTED_RRN]" in redacted


def test_document_classification_uses_weighted_layout_keywords() -> None:
    receipt_text = "금액산정내용 납부한 금액 카드 수납자 진단서 발급시 필요구비서류"
    diagnosis_text = "질병분류기호 임상적추정 최종진단 치료 내용 및 향후 치료에 대한 소견"
    surgery_text = "수化술확인서 수化술일자 수化술명 위와 같이 확인함"

    assert classify_document_from_text(receipt_text)[0] == "medical_bill_receipt"
    assert classify_document_from_text(diagnosis_text)[0] == "diagnosis_certificate"
    assert classify_document_from_text(surgery_text)[0] == "surgery_certificate"


def test_detail_row_normalization_handles_shifted_code_name_columns() -> None:
    cells = [
        OcrCell("r0c0", "p001", 0, 0, [0, 0, 20, 10], "항목"),
        OcrCell("r0c1", "p001", 0, 1, [20, 0, 40, 10], "일자"),
        OcrCell("r0c3", "p001", 0, 3, [60, 0, 80, 10], "코드"),
        OcrCell("r0c4", "p001", 0, 4, [80, 0, 180, 10], "명칭"),
        OcrCell("r0c5", "p001", 0, 5, [180, 0, 210, 10], "금액"),
        OcrCell("r0c6", "p001", 0, 6, [210, 0, 240, 10], "횟수"),
        OcrCell("r0c7", "p001", 0, 7, [240, 0, 270, 10], "일수"),
        OcrCell("r0c8", "p001", 0, 8, [270, 0, 320, 10], "총액"),
        OcrCell("r1c1", "p001", 1, 1, [20, 10, 60, 30], "20260325"),
        OcrCell("r1c3", "p001", 1, 3, [60, 10, 80, 30], "L1213"),
        OcrCell("r1c4", "p001", 1, 4, [80, 10, 180, 30], "척추마취관리기본"),
        OcrCell("r1c5", "p001", 1, 5, [180, 10, 210, 30], "117,170"),
        OcrCell("r1c6", "p001", 1, 6, [210, 10, 240, 30], "1"),
        OcrCell("r1c7", "p001", 1, 7, [240, 10, 270, 30], "1"),
        OcrCell("r1c8", "p001", 1, 8, [270, 10, 320, 30], "117,170"),
        OcrCell("r1c9", "p001", 1, 9, [320, 10, 360, 30], "23,434"),
        OcrCell("r1c10", "p001", 1, 10, [360, 10, 400, 30], "93,736"),
        OcrCell("r1c11", "p001", 1, 11, [400, 10, 440, 30], "0"),
        OcrCell("r1c12", "p001", 1, 12, [440, 10, 480, 30], "0"),
    ]
    table = OcrTable("p001_t001", "p001", [0, 0, 480, 30], 2, 13, cells)

    rows, issues = normalize_detail_rows(table, source_file="sample.jpg", page_label="1")

    assert issues == []
    assert rows[0].raw_code == "L1213"
    assert rows[0].raw_name == "척추마취관리기본"
    assert rows[0].validation_status == "verified"


def test_detail_row_normalization_keeps_digit_containing_service_name() -> None:
    cells = [
        OcrCell("r0c0", "p001", 0, 0, [0, 0, 20, 10], "항목"),
        OcrCell("r0c1", "p001", 0, 1, [20, 0, 40, 10], "일자"),
        OcrCell("r0c2", "p001", 0, 2, [40, 0, 70, 10], "코드"),
        OcrCell("r0c3", "p001", 0, 3, [70, 0, 180, 10], "명칭"),
        OcrCell("r0c4", "p001", 0, 4, [180, 0, 210, 10], "금액"),
        OcrCell("r0c5", "p001", 0, 5, [210, 0, 240, 10], "횟수"),
        OcrCell("r0c6", "p001", 0, 6, [240, 0, 270, 10], "일수"),
        OcrCell("r0c7", "p001", 0, 7, [270, 0, 320, 10], "총액"),
        OcrCell("r1c0", "p001", 1, 0, [0, 10, 20, 30], "입원료"),
        OcrCell("r1c1", "p001", 1, 1, [20, 10, 40, 30], "20260324"),
        OcrCell("r1c2", "p001", 1, 2, [40, 10, 70, 30], "ABX12"),
        OcrCell("r1c3", "p001", 1, 3, [70, 10, 180, 30], "2인실 병실차액"),
        OcrCell("r1c4", "p001", 1, 4, [180, 10, 210, 30], "170000"),
        OcrCell("r1c5", "p001", 1, 5, [210, 10, 240, 30], "1"),
        OcrCell("r1c6", "p001", 1, 6, [240, 10, 270, 30], "3"),
        OcrCell("r1c7", "p001", 1, 7, [270, 10, 320, 30], "510000"),
        OcrCell("r1c8", "p001", 1, 8, [320, 10, 360, 30], "0"),
        OcrCell("r1c9", "p001", 1, 9, [360, 10, 400, 30], "0"),
        OcrCell("r1c10", "p001", 1, 10, [400, 10, 440, 30], "0"),
        OcrCell("r1c11", "p001", 1, 11, [440, 10, 480, 30], "510000"),
    ]
    table = OcrTable("p001_t001", "p001", [0, 0, 480, 30], 2, 12, cells)

    rows, issues = normalize_detail_rows(table, source_file="sample.jpg", page_label="1")

    assert issues == []
    assert rows[0].raw_code == "ABX12"
    assert rows[0].raw_name == "2인실 병실차액"
    assert rows[0].validation_status == "verified"


def test_detail_row_normalization_does_not_treat_far_total_as_unit_amount() -> None:
    cells = [
        OcrCell("r0c0", "p001", 0, 0, [0, 0, 20, 10], "항목"),
        OcrCell("r0c1", "p001", 0, 1, [20, 0, 40, 10], "일자"),
        OcrCell("r0c2", "p001", 0, 2, [40, 0, 70, 10], "코드"),
        OcrCell("r0c3", "p001", 0, 3, [70, 0, 180, 10], "명칭"),
        OcrCell("r0c4", "p001", 0, 4, [180, 0, 210, 10], "금액"),
        OcrCell("r0c5", "p001", 0, 5, [210, 0, 240, 10], "횟수"),
        OcrCell("r0c6", "p001", 0, 6, [240, 0, 270, 10], "일수"),
        OcrCell("r0c7", "p001", 0, 7, [270, 0, 320, 10], "총액"),
        OcrCell("r1c1", "p001", 1, 1, [20, 10, 40, 30], "20260327"),
        OcrCell("r1c2", "p001", 1, 2, [40, 10, 70, 30], "D000201"),
        OcrCell("r1c3", "p001", 1, 3, [70, 10, 180, 30], "WBC Count"),
        OcrCell("r1c4", "p001", 1, 4, [180, 10, 210, 30], ""),
        OcrCell("r1c5", "p001", 1, 5, [210, 10, 240, 30], ""),
        OcrCell("r1c6", "p001", 1, 6, [240, 10, 270, 30], ""),
        OcrCell("r1c7", "p001", 1, 7, [270, 10, 320, 30], "1,220"),
        OcrCell("r1c8", "p001", 1, 8, [320, 10, 360, 30], "244"),
        OcrCell("r1c9", "p001", 1, 9, [360, 10, 400, 30], "976"),
    ]
    table = OcrTable("p001_t001", "p001", [0, 0, 480, 30], 2, 10, cells)

    rows, _issues = normalize_detail_rows(table, source_file="sample.jpg", page_label="1")

    assert rows[0].raw_name == "WBC Count"
    assert rows[0].unit_amount == ""
    assert rows[0].total_amount == "1220"
