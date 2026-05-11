"""Vision LLM-based refinement for surgery grade table cells."""

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
GRADE_ROLES = ("1-3종", "1-5종", "신1-5종")
ALLOWED_VALUES_BY_ROLE = {
    "1-3종": {"N", "1", "2", "3"},
    "1-5종": {"N", "1", "2", "3", "4", "5"},
    "신1-5종": {"N", "1", "2", "3", "4", "5"},
}
DEFAULT_NUMERIC_VISION_MODEL = "gpt-4.1"
CORRECTION_REASON = "complete_surgery_grade_group"
VISION_PROMPT = """당신은 보험 약관 표의 수술종수 컬럼 값을 판독하는 전문가입니다.
첨부 이미지는 같은 표의 전체 크롭과 수술종수 컬럼 영역 확대 크롭입니다.

이 표에서 수술종수 3개 컬럼은 도메인 규칙상 다음 둘 중 하나여야 합니다.
- 그림/공백 행: 3개 수술종수 컬럼이 모두 공란
- 텍스트 행: 3개 수술종수 컬럼이 모두 N 또는 숫자로 채워짐

아래 후보 행의 blank("") 또는 잘못 인식된 값이 실제 이미지에서 무엇인지 판독하세요.
세로선처럼 보이는 아주 얇은 획도 숫자 "1"일 수 있습니다.

규칙:
- 수술종수 이외 컬럼은 절대 변경하지 마세요.
- 후보 행의 대상 셀마다 가능한 한 반드시 값을 판정하세요.
- 허용 값:
  - 1-3종 역할 컬럼: "N", "1", "2", "3"
  - 1-5종 / 신1-5종 역할 컬럼: "N", "1", "2", "3", "4", "5"
- JSON 형식만 반환하고 다른 설명은 출력하지 마세요.
- table_json 전체를 에코하지 마세요. 변경/판독불가 셀만 아래 형식으로 반환하세요.

수술종수 컬럼 역할:
__GRADE_COLUMN_ROLES__

후보 row_index 및 각 행의 수술명:
__CANDIDATE_ROWS__

반환 형식 (이 JSON 구조만 반환):
{
  "corrections": [
    {"row_index": <int>, "col": "<컬럼명>", "to": "<값>", "confidence": "high|medium|low"}
  ],
  "unresolved": [
    {"row_index": <int>, "col": "<컬럼명>", "reason": "not_readable"}
  ]
}
"""


class NumericCellRefinerAuthError(RuntimeError):
    """Raised when the Vision API rejects authentication."""


def _is_numeric_column(header: str) -> bool:
    return any(re.search(pattern, header) for pattern in NUMERIC_COL_PATTERNS)


def _normalize_grade_value(value: Any) -> str:
    text = str(value or "").strip().upper()
    return "N" if text == "N" else text


def _has_context_text(row: dict) -> bool:
    return bool(str(row.get("수술명", "")).strip() or str(row.get("수술해설", "")).strip())


def _is_figure_row(row: dict) -> bool:
    joined = " ".join(str(row.get(key, "")) for key in ("수술명", "수술해설"))
    return "[그림]" in joined


def _grade_column_roles(headers: list[str]) -> list[dict]:
    """Return the three surgery grade columns with their semantic roles."""

    indexed_headers = {header: index for index, header in enumerate(headers)}
    if all(role in indexed_headers for role in GRADE_ROLES):
        return [
            {"col": role, "role": role, "allowed": ALLOWED_VALUES_BY_ROLE[role]}
            for role in GRADE_ROLES
        ]

    surgery_cols = [header for header in headers if re.search(r"^수술종수", header)]
    if len(surgery_cols) >= 3:
        return [
            {"col": surgery_cols[index], "role": role, "allowed": ALLOWED_VALUES_BY_ROLE[role]}
            for index, role in enumerate(GRADE_ROLES)
        ]

    numeric_cols = [header for header in headers if _is_numeric_column(header)]
    role_map = []
    for header in numeric_cols:
        if header == "1-3종" or re.search(r"^1-[0-9]+종$", header):
            role = "1-3종"
        elif header == "신1-5종" or re.search(r"^신[0-9]+-[0-9]+종$", header):
            role = "신1-5종"
        else:
            role = "1-5종"
        role_map.append({"col": header, "role": role, "allowed": ALLOWED_VALUES_BY_ROLE[role]})
    return role_map[:3]


def _is_valid_for_role(value: Any, role: dict) -> bool:
    return _normalize_grade_value(value) in role["allowed"]


def _needs_refinement(row: dict, grade_roles: list[dict]) -> bool:
    if not _has_context_text(row) or _is_figure_row(row):
        return False

    values = [_normalize_grade_value(row.get(role["col"], "")) for role in grade_roles]
    if all(value == "" for value in values):
        return True
    if any(value == "" for value in values):
        return True
    return any(not _is_valid_for_role(row.get(role["col"], ""), role) for role in grade_roles)


def _candidate_row_indexes(table_json: dict, grade_roles: list[dict]) -> list[int]:
    indexes: list[int] = []
    rows = table_json.get("rows", [])
    if not isinstance(rows, list) or len(grade_roles) != 3:
        return indexes
    for index, row in enumerate(rows):
        if isinstance(row, dict) and _needs_refinement(row, grade_roles):
            indexes.append(index)
    return indexes


def _target_cells_for_row(row: dict, grade_roles: list[dict]) -> list[str]:
    targets: list[str] = []
    for role in grade_roles:
        col = role["col"]
        value = _normalize_grade_value(row.get(col, ""))
        if value == "" or value not in role["allowed"]:
            targets.append(col)
    return targets


def _same_table_shape_allow_metadata(original: dict, candidate: dict) -> bool:
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
    metadata_keys = {"_corrections", "_unresolved"}
    for row in candidate_rows:
        if not isinstance(row, dict):
            return False
        row_keys = set(row.keys()) - metadata_keys
        if row_keys != expected_keys:
            return False
    return True


def _crop_grade_columns_image(page_image: Image.Image, bbox: list[int]) -> Image.Image:
    table_crop = _crop_table_image(page_image, bbox)
    width, height = table_crop.size
    if width <= 1 or height <= 1:
        return table_crop
    left = max(0, int(width * 0.58))
    grade_crop = table_crop.crop((left, 0, width, height))
    return grade_crop.resize((grade_crop.width * 2, grade_crop.height * 2))


def _build_prompt(table_json: dict, grade_roles: list[dict], candidate_indexes: list[int]) -> str:
    role_payload = [
        {
            "col": role["col"],
            "role": role["role"],
            "allowed_values": sorted(role["allowed"]),
        }
        for role in grade_roles
    ]
    rows = table_json.get("rows", [])
    candidate_rows_summary: list[dict] = []
    for index in candidate_indexes:
        row = rows[index] if index < len(rows) and isinstance(rows[index], dict) else {}
        candidate_rows_summary.append(
            {
                "row_index": index,
                "수술명": str(row.get("수술명", ""))[:50],
                "현재값": {role["col"]: str(row.get(role["col"], "")) for role in grade_roles},
            }
        )
    return (
        VISION_PROMPT.replace("__GRADE_COLUMN_ROLES__", json.dumps(role_payload, ensure_ascii=False, indent=2))
        .replace("__CANDIDATE_ROWS__", json.dumps(candidate_rows_summary, ensure_ascii=False, indent=2))
    )


def _call_vision(
    block: LayoutBlock,
    page_image: Image.Image,
    client: Any,
    model: str,
    prompt: str,
) -> dict | None:
    full_image_b64 = _encode_image(_crop_table_image(page_image, block.bbox))
    grade_image_b64 = _encode_image(_crop_grade_columns_image(page_image, block.bbox))
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{full_image_b64}"}},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{grade_image_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    except Exception as exc:
        if _is_auth_error(exc):
            raise NumericCellRefinerAuthError("OpenAI Vision API authentication failed") from exc
        LOGGER.warning("Numeric cell refinement failed: %s", exc)
        return None
    return _extract_json_object(_response_content(response))


def _extract_valid_corrections_and_unresolved(
    original: dict,
    delta: dict,
    grade_roles: list[dict],
    candidate_indexes: list[int],
) -> tuple[list[dict], list[dict]]:
    corrections: list[dict] = []
    unresolved: list[dict] = []
    original_rows = original.get("rows", [])
    candidate_index_set = set(candidate_indexes)
    roles_by_col = {role["col"]: role for role in grade_roles}
    target_cols_by_row = {
        row_index: set(_target_cells_for_row(original_rows[row_index], grade_roles))
        for row_index in candidate_indexes
        if row_index < len(original_rows)
    }
    resolved: set[tuple[int, str]] = set()

    for item in delta.get("corrections", []) or []:
        if not isinstance(item, dict):
            continue
        row_index = item.get("row_index")
        col = str(item.get("col", ""))
        to_value = _normalize_grade_value(item.get("to", ""))
        if not isinstance(row_index, int) or row_index not in candidate_index_set:
            continue
        if col not in roles_by_col or col not in target_cols_by_row.get(row_index, set()):
            continue
        original_value = str(original_rows[row_index].get(col, "")) if row_index < len(original_rows) else ""
        role = roles_by_col[col]
        if to_value not in role["allowed"]:
            unresolved.append(
                {
                    "row_index": row_index,
                    "col": col,
                    "from": original_value,
                    "reason": "invalid_vision_value",
                }
            )
            continue
        corrections.append(
            {
                "row_index": row_index,
                "col": col,
                "from": original_value,
                "to": to_value,
                "method": "vision_llm",
                "reason": CORRECTION_REASON,
                "confidence": str(item.get("confidence", "medium")),
            }
        )
        resolved.add((row_index, col))

    for item in delta.get("unresolved", []) or []:
        if not isinstance(item, dict):
            continue
        row_index = item.get("row_index")
        col = str(item.get("col", ""))
        if not isinstance(row_index, int) or (row_index, col) in resolved:
            continue
        if row_index not in candidate_index_set or col not in target_cols_by_row.get(row_index, set()):
            continue
        unresolved.append(
            {
                "row_index": row_index,
                "col": col,
                "from": str(original_rows[row_index].get(col, "")) if row_index < len(original_rows) else "",
                "reason": str(item.get("reason", "not_readable")),
            }
        )

    for row_index, target_cols in target_cols_by_row.items():
        for col in sorted(target_cols):
            if (row_index, col) in resolved:
                continue
            if any(item["row_index"] == row_index and item["col"] == col for item in unresolved):
                continue
            unresolved.append(
                {
                    "row_index": row_index,
                    "col": col,
                    "from": str(original_rows[row_index].get(col, "")) if row_index < len(original_rows) else "",
                    "reason": "missing_vision_correction",
                }
            )
    return corrections, unresolved


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


def _parse_with_retry(
    block: LayoutBlock,
    page_image: Image.Image,
    client: Any,
    model: str,
    prompt: str,
) -> dict | None:
    for attempt in range(2):
        parsed = _call_vision(block, page_image, client, model, prompt)
        if _is_valid_delta(parsed):
            return parsed
        LOGGER.warning("Numeric cell refinement returned invalid delta format (attempt %s)", attempt + 1)
    return None


def _is_valid_delta(parsed: dict | None) -> bool:
    """Vision 응답이 corrections-only delta 형식인지 검증한다."""

    if not isinstance(parsed, dict):
        return False
    corrections = parsed.get("corrections")
    unresolved = parsed.get("unresolved")
    if corrections is None and unresolved is None:
        return False
    if corrections is not None and not isinstance(corrections, list):
        return False
    if unresolved is not None and not isinstance(unresolved, list):
        return False
    return True


def _refine_single_table(block: LayoutBlock, page_image: Image.Image, client: Any, model: str) -> LayoutBlock:
    if not block.table_json:
        return block

    headers = [str(header) for header in block.table_json.get("headers", [])]
    grade_roles = _grade_column_roles(headers)
    if len(grade_roles) != 3:
        return block

    candidate_indexes = _candidate_row_indexes(block.table_json, grade_roles)
    if not candidate_indexes:
        return block

    prompt = _build_prompt(block.table_json, grade_roles, candidate_indexes)
    parsed = _parse_with_retry(block, page_image, client, model, prompt)
    if parsed is None:
        return block

    corrections, unresolved = _extract_valid_corrections_and_unresolved(
        block.table_json,
        parsed,
        grade_roles,
        candidate_indexes,
    )
    if not corrections and not unresolved:
        return block

    updated_table = _apply_corrections(block.table_json, corrections)
    raw = dict(block.raw or {})
    raw["numeric_candidate_rows"] = candidate_indexes
    if corrections:
        raw["numeric_corrections"] = corrections
        raw["numeric_refined"] = True
    if unresolved:
        raw["numeric_unresolved_cells"] = unresolved
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
    model: str = DEFAULT_NUMERIC_VISION_MODEL,
) -> list[LayoutBlock]:
    """수술종수 3개 컬럼 그룹의 누락/invalid 셀을 Vision LLM으로 재판독한다."""

    refined: list[LayoutBlock] = []
    for block in blocks:
        if block.block_type != "table":
            refined.append(block)
            continue
        refined.append(_refine_single_table(block, page_image, client, model))
    return refined
