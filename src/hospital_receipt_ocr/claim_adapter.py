"""Convert verified OCR rows into ClaimItemInput-compatible dictionaries."""

from __future__ import annotations

import json

from .models import DetailRow


def detail_rows_to_claim_items(detail_rows: list[DetailRow]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for row in detail_rows:
        if row.validation_status != "verified":
            continue
        if not row.total_amount or not row.raw_name:
            continue
        items.append(
            {
                "line_id": row.row_id,
                "input_name": row.raw_name,
                "input_code": row.normalized_code,
                "claimed_amount": row.total_amount,
                "insured_copay_amount": row.insured_copay_amount,
                "nonpay_amount": row.nonpay_amount,
                "quantity": "1",
                "user_category_hint": row.item_group,
                "extra_info": json.dumps(
                    {
                        "source_file": row.source_file,
                        "page_label": row.page_label,
                        "source_cells": row.source_cells,
                        "unit_amount": row.unit_amount,
                        "count": row.count,
                        "days": row.days,
                        "bbox": row.bbox,
                    },
                    ensure_ascii=False,
                ),
                "is_prescription": False,
            }
        )
    return items
