"""Vision LLM-based refinement for blank surgery grade cells."""

from __future__ import annotations

from dataclasses import replace
import json
import logging
import re
from typing import Any

from PIL import Image

from src.parser.clova_ocr import _table_json_to_html, _table_to_text
from src.parser.ocr_engine import LayoutBlock
from src.parser.table_vision_cleaner import (
    _crop_table_image,
    _encode_image,
    _extract_json_object,
    _is_auth_error,
    _response_content,
)

LOGGER = logging.getLogger(__name__)

NUMERIC_COL_PATTERNS = [
    r"^(1|2|3)-[0-9]+종$",
    r"^신[0-9]+-[0-9]+종$",
    r"^수술종수",
]
ALLOWED_VALUES = {"1", "2", "3", ""}
VISION_PROMPT = """당신은 보험 약관 표의 수술종수 컬럼 값을 판독하는 전문가입니다.
첨부 이미지는 해당 표 영역의 크롭입니다.

아래 JSON에서 blank("")로 기록된 수술종수 컬럼들이 실제 이미지에는
어떤 값(1, 2, 3 또는 공란)이 적혀 있는지 확인하여 채워주세요.

규칙:
- 허용 값: "1", "2", "3", "" (진짜 공란인 경우)
- 수술종수 이외 컬럼은 절대 변경하지 마세요.
- 표 구조(headers, row 수, key 이름)는 변경하지 마세요.
- 수정한 셀에 대해서만 rows[i]["_corrections"][col] = {"from": "", "to": "새값"} 형태로
  메타 정보를 추가하세요. ("_corrections" 키는 rows 내 임의 추가 허용)
- JSON 형식만 반환하고 다른 설명은 출력하지 마세요.

현재 table_json:
__TABLE_JSON__
"""


class NumericCellRefinerAuthError(RuntimeError):
    """Raised when the Vision API rejects authentication."""


def _is_numeric_column(header: str) -> bool:
    return any(re.search(pattern, header) for pattern in NUMERIC_COL_PATTERNS)


def _numeric_columns(headers: list[str]) -> list[str]:
    return [header for header in headers if _is_numeric_column(header)]


def _has_context_text(row: dict) -> bool:
    return bool(str(row.get("수술명", "")).strip() or str(row.get("수술해설", "")).strip())


def _candidate_row_indexes(table_json: dict, numeric_cols: list[str]) -> list[int]:
    indexes: list[int] = []
    rows = table_json.get("rows", [])
    if not isinstance(rows, list):
        return indexes
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if not _has_context_text(row):
            continue
        if all(str(row.get(col, "")).strip() == "" for col in numeric_cols):
            indexes.append(index)
    return indexes


def _same_table_shape_allow_corrections(original: dict, candidate: dict) -> bool:
    original_headers = [str(header) for header in original.get("headers", [])]
    candidate_headers = [str(header) for header in candidate.get("headers", [])]
    if candidate_headers != original_headers:
        return False

    original_rows = original.get("rows", [])
    candidate_rows = candidate.get("rows", [])
    if not isinstance(original_rows, list) or not isinstance(candidate_rows, list):
        return False
    if len(candidate_rows) != len(original_rows):
        return False

    expected_keys = set(original_headers)
    for row in candidate_rows:
        if not isinstance(row, dict):
            return False
        row_keys = set(row.keys())
        if "_corrections" in row_keys:
            row_keys.remove("_corrections")
        if row_keys != expected_keys:
            return False
    return True


def _extract_valid_corrections(
    original: dict,
    candidate: dict,
    numeric_cols: list[str],
    candidate_indexes: list[int],
) -> list[dict]:
    corrections: list[dict] = []
    original_rows = original.get("rows", [])
    candidate_rows = candidate.get("rows", [])
    candidate_index_set = set(candidate_indexes)
    numeric_col_set = set(numeric_cols)

    for row_index, row in enumerate(candidate_rows):
        if row_index not in candidate_index_set or not isinstance(row, dict):
            continue
        raw_corrections = row.get("_corrections")
        if not isinstance(raw_corrections, dict):
            continue
        original_row = original_rows[row_index]
        for col, change in raw_corrections.items():
            if col not in numeric_col_set or not isinstance(change, dict):
                continue
            before = str(change.get("from", ""))
            after = str(change.get("to", ""))
            if before != "" or after not in ALLOWED_VALUES:
                continue
            if str(original_row.get(col, "")).strip() != "":
                continue
            if after == "":
                continue
            corrections.append({"row_index": row_index, "col": col, "from": "", "to": after})
    return corrections


def _apply_corrections(table_json: dict, corrections: list[dict]) -> dict:
    updated = {
        "headers": [str(header) for header in table_json.get("headers", [])],
        "rows": [dict(row) for row in table_json.get("rows", [])],
    }
    for correction in corrections:
        row_index = int(correction["row_index"])
        col = str(correction["col"])
        updated["rows"][row_index][col] = str(correction["to"])
    return updated


def _refine_single_table(block: LayoutBlock, page_image: Image.Image, client: Any, model: str) -> LayoutBlock:
    if not block.table_json:
        return block

    headers = [str(header) for header in block.table_json.get("headers", [])]
    numeric_cols = _numeric_columns(headers)
    if not numeric_cols:
        return block

    candidate_indexes = _candidate_row_indexes(block.table_json, numeric_cols)
    if not candidate_indexes:
        return block

    crop = _crop_table_image(page_image, block.bbox)
    image_b64 = _encode_image(crop)
    prompt = VISION_PROMPT.replace(
        "__TABLE_JSON__",
        json.dumps(block.table_json, ensure_ascii=False, indent=2),
    )

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    except Exception as exc:
        if _is_auth_error(exc):
            raise NumericCellRefinerAuthError("OpenAI Vision API authentication failed") from exc
        LOGGER.warning("Numeric cell refinement failed: %s", exc)
        return block

    parsed = _extract_json_object(_response_content(response))
    if parsed is None or not _same_table_shape_allow_corrections(block.table_json, parsed):
        LOGGER.warning("Numeric cell refinement returned invalid JSON shape")
        return block

    corrections = _extract_valid_corrections(block.table_json, parsed, numeric_cols, candidate_indexes)
    if not corrections:
        return block

    updated_table = _apply_corrections(block.table_json, corrections)
    raw = dict(block.raw or {})
    raw["numeric_corrections"] = corrections
    raw["numeric_refined"] = True
    return replace(
        block,
        table_json=updated_table,
        text=_table_to_text(updated_table),
        html=_table_json_to_html(updated_table),
        raw=raw,
    )


def refine_numeric_cells(
    blocks: list[LayoutBlock],
    page_image: Image.Image,
    client: Any,
    model: str = "gpt-4o-mini",
) -> list[LayoutBlock]:
    """수술종수 컬럼이 전부 blank인 행을 Vision LLM으로 재판독한다."""

    refined: list[LayoutBlock] = []
    for block in blocks:
        if block.block_type != "table":
            refined.append(block)
            continue
        refined.append(_refine_single_table(block, page_image, client, model))
    return refined
