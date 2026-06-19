from __future__ import annotations


def test_verified_row_is_promoted_to_claim_draft():
    from src.hospital_receipt_ocr.claim_adapter import build_claim_item_drafts

    rows = [
        {
            "row_id": "row-1",
            "item_name": "진찰료",
            "total_amount": 13370,
            "source": {"document_id": "doc-1", "page": 1, "bbox": [1, 2, 3, 4]},
            "validation": {"status": "verified", "issues": []},
        }
    ]

    drafts = build_claim_item_drafts(rows)

    assert drafts == [
        {
            "source_row_id": "row-1",
            "item_name": "진찰료",
            "claimed_amount": 13370,
            "quantity": 1,
            "status": "draft_verified",
        }
    ]


def test_unverified_row_is_not_promoted_to_claim_draft():
    from src.hospital_receipt_ocr.claim_adapter import build_claim_item_drafts

    rows = [
        {
            "row_id": "row-2",
            "item_name": "MRI진단료",
            "total_amount": 490000,
            "source": {"document_id": "doc-1", "page": 2, "bbox": [1, 2, 3, 4]},
            "validation": {"status": "review_required", "issues": ["component_sum_mismatch"]},
        }
    ]

    assert build_claim_item_drafts(rows) == []


def test_verified_row_without_source_key_is_not_promoted_to_claim_draft():
    from src.hospital_receipt_ocr.claim_adapter import build_claim_item_drafts

    rows = [
        {
            "item_name": "MRI진단료",
            "total_amount": 490000,
            "source": {"document_id": "doc-1", "page": 2, "bbox": [1, 2, 3, 4]},
            "validation": {"status": "verified", "issues": []},
        }
    ]

    assert build_claim_item_drafts(rows) == []


def test_zero_indexed_source_page_can_be_promoted_to_claim_draft():
    from src.hospital_receipt_ocr.claim_adapter import build_claim_item_drafts

    rows = [
        {
            "row_id": "row-3",
            "item_name": "진찰료",
            "total_amount": 13370,
            "source": {"document_id": "doc-1", "page": 0, "bbox": [1, 2, 3, 4]},
            "validation": {"status": "verified", "issues": []},
        }
    ]

    assert build_claim_item_drafts(rows)[0]["source_row_id"] == "row-3"


def test_validation_failure_can_be_recorded_as_human_task():
    from src.hospital_receipt_ocr.validation import build_human_task

    task = build_human_task({"row_id": "row-4"}, "component_sum_mismatch")

    assert task == {
        "source_row_id": "row-4",
        "reason": "component_sum_mismatch",
        "status": "review_required",
        "message": "OCR row requires human review before claim calculation input.",
    }
