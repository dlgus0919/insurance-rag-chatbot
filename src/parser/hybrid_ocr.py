"""Hybrid OCR: PP-Structure 레이아웃 + PaddleOCR Korean."""

from __future__ import annotations

import numpy as np

from src.parser.ocr_engine import (
    LayoutBlock,
    _extract_table_twopass,
    _flatten_ocr_result,
    _get_korean_ocr,
    _table_html_to_text,
    run_easyocr_fallback,
)
from src.parser.ocr_postprocess import normalize_ocr_text
from src.parser.ocr_preprocessor import PreprocessResult


def _hybrid_text_block(crop, bbox: tuple[int, int, int, int], block_type: str, korean_ocr) -> LayoutBlock | None:
    arr = np.array(crop)
    text_raw, confidence = _flatten_ocr_result(korean_ocr.ocr(arr, cls=False))
    text = normalize_ocr_text(text_raw)
    if not text.strip():
        return None
    return LayoutBlock(
        block_type=block_type,
        bbox=list(bbox),
        text=text,
        confidence=confidence if confidence > 0 else None,
        source_method="ocr_ppstructure_twopass",
    )


def _hybrid_table_block(crop, bbox: tuple[int, int, int, int], korean_ocr) -> LayoutBlock | None:
    arr = np.array(crop)
    x1, y1 = bbox[0], bbox[1]
    html, table_json, _ = _extract_table_twopass(arr, korean_ocr, offset=(x1, y1))
    text = _table_html_to_text(html)
    if not text.strip():
        return None
    return LayoutBlock(
        block_type="table",
        bbox=list(bbox),
        text=text,
        html=html,
        table_json=table_json,
        confidence=table_json.get("avg_confidence"),
        source_method="ocr_ppstructure_twopass",
    )


def hybrid_ocr_page(prep: PreprocessResult) -> list[LayoutBlock]:
    """전처리 결과에서 Hybrid OCR을 수행한다."""

    korean_ocr = _get_korean_ocr()
    blocks: list[LayoutBlock] = []

    for region in prep.regions:
        if region.block_type == "figure":
            continue

        x1, y1, x2, y2 = region.bbox
        crop = prep.masked_image.crop((x1, y1, x2, y2))

        if region.block_type == "table":
            block = _hybrid_table_block(crop, region.bbox, korean_ocr)
        else:
            block = _hybrid_text_block(crop, region.bbox, region.block_type, korean_ocr)
        if block is not None:
            blocks.append(block)

    if not blocks:
        return run_easyocr_fallback(prep.masked_image)
    blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    return blocks

