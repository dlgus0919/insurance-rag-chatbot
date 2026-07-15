from __future__ import annotations

from scripts.eval_hospital_receipt_claim_batch import (
    build_claim_context,
    build_claim_items,
    flatten_line_results,
)


def test_build_claim_items_preserves_source_metadata() -> None:
    payload = {
        "claim_items": [
            {
                "line_id": "detail_p001_r001",
                "input_name": "체질침술료",
                "input_code": "AA254",
                "claimed_amount": 13370,
                "insured_copay_amount": 2674,
                "nonpay_amount": 0,
                "quantity": 1,
                "user_category_hint": "source_amount_split:insured_copay",
                "ready_for_auto_calculation": True,
                "is_prescription": True,
                "extra_info": {
                    "source_file": "CamScanner 2026. 6. 9. 15.00_1.jpg",
                    "page_label": "1 / 9",
                    "source_row_id": "detail_p001_r001",
                    "item_group": "진찰료",
                    "service_date": "20260324-20260324",
                },
            }
        ]
    }

    items, metadata = build_claim_items(payload)

    assert len(items) == 1
    assert items[0].line_id == "detail_p001_r001"
    assert items[0].claimed_amount == "13370"
    assert items[0].insured_copay_amount == "2674"
    assert items[0].quantity == "1"
    assert items[0].is_prescription is True
    assert metadata["detail_p001_r001"]["page_label"] == "1 / 9"
    assert metadata["detail_p001_r001"]["ready_for_auto_calculation"] is True


def test_build_claim_items_uses_single_amount_when_split_amounts_are_zero() -> None:
    payload = {
        "claim_items": [
            {
                "line_id": "detail_p002_r001",
                "input_name": "비급여 치료재료",
                "claimed_amount": 72000,
                "insured_copay_amount": 0,
                "nonpay_amount": 0,
                "quantity": 1,
            }
        ]
    }

    items, _ = build_claim_items(payload)

    assert items[0].claimed_amount == "72000"
    assert items[0].insured_copay_amount == ""
    assert items[0].nonpay_amount == ""


def test_build_claim_context_defaults_to_latest_supported_generation() -> None:
    payload = {
        "claim_case_context": {
            "treatment_date": "2026-03-25",
            "visit_type": "hospitalization",
            "diagnosis_code": ["S8352", "S8329"],
            "diagnosis_name": ["전십자인대의 파열, 우측", "내측 반달연골의 파열, 우측"],
            "policy_generation": None,
            "situation_note": "입원기간 2026-03-24~2026-03-27",
        }
    }

    context = build_claim_context(payload)

    assert context.policy_generation == "5th"
    assert context.visit_type == "hospitalization"
    assert context.diagnosis_code == "S8352, S8329"
    assert "전십자인대" in context.diagnosis_name


def test_flatten_line_results_adds_practitioner_columns() -> None:
    line_results = [
        {
            "line_id": "detail_p001_r001",
            "input_name": "체질침술료",
            "category": "급여",
            "claimed_amount": "13370",
            "deductible": "2674",
            "payable_amount": "10696",
            "calculation_status": "calculated",
            "requires_review": False,
            "review_reasons": [],
            "rule_summary": "급여 본인부담금 계산",
        }
    ]
    metadata = {
        "detail_p001_r001": {
            "source_file": "CamScanner 2026. 6. 9. 15.00_1.jpg",
            "page_label": "1 / 9",
            "source_row_id": "detail_p001_r001",
            "item_group": "진찰료",
            "service_date": "20260324-20260324",
            "ready_for_auto_calculation": True,
        }
    }

    rows = flatten_line_results(line_results, metadata)

    assert rows[0]["page_label"] == "1 / 9"
    assert rows[0]["input_name"] == "체질침술료"
    assert rows[0]["payable_amount"] == "10696"
    assert rows[0]["practitioner_grade"] == ""
    assert rows[0]["practitioner_comment"] == ""
    assert rows[0]["corrected_payable_amount"] == ""
