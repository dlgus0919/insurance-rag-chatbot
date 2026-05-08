"""CLOVA OCR API 클라이언트 + bbox 기반 표 재구성."""

from __future__ import annotations

import io
import json
import os
import uuid
from typing import Any

import requests

from src.parser.ocr_engine import LayoutBlock

_REQUEST_TIMEOUT_SEC = 60
_MAX_RETRIES = 1


class ClovaOcrError(RuntimeError):
    """CLOVA OCR 호출/파싱 실패."""


def _vertices_to_bbox(vertices: list[dict]) -> tuple[int, int, int, int]:
    if not vertices:
        return (0, 0, 0, 0)
    xs = [int(v.get("x", 0)) for v in vertices]
    ys = [int(v.get("y", 0)) for v in vertices]
    return (min(xs), min(ys), max(xs), max(ys))


def _field_bbox(field: dict) -> tuple[float, float, float, float]:
    vertices = field.get("boundingPoly", {}).get("vertices", [])
    if not vertices:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [float(v.get("x", 0.0)) for v in vertices]
    ys = [float(v.get("y", 0.0)) for v in vertices]
    return min(xs), min(ys), max(xs), max(ys)


def _field_center_y(field: dict) -> float:
    x1, y1, x2, y2 = _field_bbox(field)
    return (y1 + y2) / 2.0


def _field_center_x(field: dict) -> float:
    x1, y1, x2, y2 = _field_bbox(field)
    return (x1 + x2) / 2.0


def _unique_headers(headers: list[str], width: int) -> list[str]:
    normalized: list[str] = []
    seen: dict[str, int] = {}
    for index in range(width):
        header = headers[index] if index < len(headers) else ""
        header = " ".join(str(header).split()) or f"col_{index + 1}"
        count = seen.get(header, 0)
        seen[header] = count + 1
        normalized.append(header if count == 0 else f"{header}_{count + 1}")
    return normalized


def _cell_words_text(cell: dict) -> str:
    words: list[str] = []
    for line in cell.get("cellTextLines", []):
        for word in line.get("words", []):
            text = str(word.get("text", "")).strip()
            if text:
                words.append(text)
    return " ".join(words)


def _table_to_json(table: dict) -> dict:
    """CLOVA tables 필드가 있을 때 table JSON으로 변환한다."""

    cells = table.get("cells", [])
    if not cells:
        return {"headers": [], "rows": []}

    max_row = 0
    max_col = 0
    for cell in cells:
        row_index = int(cell.get("rowIndex", 0))
        col_index = int(cell.get("columnIndex", 0))
        row_span = max(1, int(cell.get("rowSpan", 1)))
        col_span = max(1, int(cell.get("columnSpan", 1)))
        max_row = max(max_row, row_index + row_span - 1)
        max_col = max(max_col, col_index + col_span - 1)

    grid: list[list[str]] = [[""] * (max_col + 1) for _ in range(max_row + 1)]
    for cell in cells:
        row_index = int(cell.get("rowIndex", 0))
        col_index = int(cell.get("columnIndex", 0))
        row_span = max(1, int(cell.get("rowSpan", 1)))
        col_span = max(1, int(cell.get("columnSpan", 1)))
        value = _cell_words_text(cell)
        for row in range(row_index, min(len(grid), row_index + row_span)):
            for col in range(col_index, min(len(grid[row]), col_index + col_span)):
                if not grid[row][col]:
                    grid[row][col] = value

    headers = _unique_headers(grid[0] if grid else [], len(grid[0]) if grid else 0)
    rows: list[dict] = []
    for raw_row in grid[1:]:
        padded = raw_row + [""] * max(0, len(headers) - len(raw_row))
        rows.append(dict(zip(headers, padded[: len(headers)])))
    return {"headers": headers, "rows": rows}


def _table_to_text(table_json: dict) -> str:
    headers = [str(value) for value in table_json.get("headers", [])]
    parts: list[str] = []
    if headers:
        parts.append(" | ".join(headers))
    for row in table_json.get("rows", []):
        values = [str(row.get(header, "")) for header in headers]
        parts.append(" | ".join(values))
    return "\n".join(parts)


def _table_json_to_html(table_json: dict) -> str:
    headers = [str(value) for value in table_json.get("headers", [])]
    lines = ["<table>"]
    if headers:
        lines.append("<tr>" + "".join(f"<td>{value}</td>" for value in headers) + "</tr>")
    for row in table_json.get("rows", []):
        values = [str(row.get(header, "")) for header in headers]
        lines.append("<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>")
    lines.append("</table>")
    return "".join(lines)


def _load_clova_env() -> tuple[str, str]:
    url = os.getenv("CLOVA_OCR_URL", "").strip()
    secret = os.getenv("CLOVA_OCR_SECRET", "").strip()
    if not url or not secret:
        raise ClovaOcrError("CLOVA_OCR_URL 또는 CLOVA_OCR_SECRET 환경변수가 설정되지 않았습니다.")
    return url, secret


def _request_clova(image, page_name: str, timeout_sec: int | None = None) -> dict:
    url, secret = _load_clova_env()

    buffer = io.BytesIO()
    rgb = image.convert("RGB") if image.mode != "RGB" else image
    rgb.save(buffer, format="JPEG", quality=95)
    buffer.seek(0)

    message = json.dumps(
        {
            "version": "V2",
            "requestId": str(uuid.uuid4()),
            "timestamp": 0,
            "images": [{"format": "jpg", "name": page_name}],
        },
        ensure_ascii=False,
    )

    request_timeout = int(timeout_sec or _REQUEST_TIMEOUT_SEC)
    response = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers={"X-OCR-SECRET": secret},
                files={
                    "message": (None, message, "application/json"),
                    "file": (f"{page_name}.jpg", buffer.getvalue(), "image/jpeg"),
                },
                timeout=request_timeout,
            )
            response.raise_for_status()
            break
        except requests.Timeout as exc:
            if attempt < _MAX_RETRIES:
                continue
            raise ClovaOcrError(f"타임아웃 재시도 초과: {exc}") from exc
        except requests.RequestException as exc:
            raise ClovaOcrError(f"API 요청 실패: {exc}") from exc

    if response is None:  # pragma: no cover
        raise ClovaOcrError("CLOVA OCR 응답을 받지 못했습니다.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ClovaOcrError("CLOVA OCR API 응답 JSON 파싱 실패") from exc

    images = payload.get("images", [])
    if not images:
        raise ClovaOcrError("CLOVA OCR 응답에 images가 없습니다.")
    image_result = images[0]
    if image_result.get("inferResult") != "SUCCESS":
        message_text = image_result.get("message", "unknown")
        raise ClovaOcrError(f"CLOVA OCR 인식 실패: {message_text}")
    return image_result


def _group_fields_into_rows(fields: list[dict], row_gap: float = 20.0) -> list[list[dict]]:
    if not fields:
        return []
    sorted_fields = sorted(fields, key=lambda field: (_field_center_y(field), _field_center_x(field)))
    rows: list[list[dict]] = [[sorted_fields[0]]]
    for field in sorted_fields[1:]:
        last_row_y = _field_center_y(rows[-1][-1])
        if abs(_field_center_y(field) - last_row_y) <= row_gap:
            rows[-1].append(field)
        else:
            rows.append([field])
    for row in rows:
        row.sort(key=_field_center_x)
    return rows


def _detect_column_x_ranges(rows: list[list[dict]], col_gap: float = 40.0) -> list[tuple[float, float]]:
    x_starts: list[float] = []
    for row in rows:
        for field in row:
            x1, _, _, _ = _field_bbox(field)
            x_starts.append(x1)
    if not x_starts:
        return []

    x_starts.sort()
    clusters: list[list[float]] = [[x_starts[0]]]
    for x in x_starts[1:]:
        if x - clusters[-1][-1] <= col_gap:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    col_ranges: list[tuple[float, float]] = []
    for cluster in clusters:
        x_min = min(cluster)
        x_max = max(cluster)
        col_ranges.append((x_min, x_max + col_gap))
    return col_ranges


def _assign_fields_to_columns(row_fields: list[dict], col_ranges: list[tuple[float, float]]) -> list[str]:
    cells = [""] * len(col_ranges)
    for field in row_fields:
        cx = _field_center_x(field)
        text = str(field.get("inferText", "")).strip()
        if not text:
            continue
        for col_index, (x_min, x_max) in enumerate(col_ranges):
            if x_min - 20 <= cx <= x_max + 20:
                sep = " " if cells[col_index] else ""
                cells[col_index] += sep + text
                break
        else:
            if not col_ranges:
                continue
            distances = [abs(cx - ((x_min + x_max) / 2.0)) for x_min, x_max in col_ranges]
            nearest = distances.index(min(distances))
            sep = " " if cells[nearest] else ""
            cells[nearest] += sep + text
    return cells


def _filter_fields_in_bbox(fields: list[dict], bbox: tuple[float, float, float, float], margin: float = 10.0) -> list[dict]:
    x1, y1, x2, y2 = bbox
    return [
        field
        for field in fields
        if (x1 - margin <= _field_center_x(field) <= x2 + margin and y1 - margin <= _field_center_y(field) <= y2 + margin)
    ]


def _field_indices_in_bbox(
    fields: list[dict], bbox: tuple[float, float, float, float], margin: float = 10.0
) -> list[int]:
    x1, y1, x2, y2 = bbox
    indices: list[int] = []
    for index, field in enumerate(fields):
        cx = _field_center_x(field)
        cy = _field_center_y(field)
        if x1 - margin <= cx <= x2 + margin and y1 - margin <= cy <= y2 + margin:
            indices.append(index)
    return indices


def reconstruct_table_from_fields(
    fields: list[dict],
    table_bbox: tuple[float, float, float, float],
    row_gap: float = 20.0,
    col_gap: float = 40.0,
) -> dict:
    """CLOVA field bbox 기반 표 JSON 재구성."""

    table_fields = _filter_fields_in_bbox(fields, table_bbox, margin=10.0)
    if not table_fields:
        return {"headers": [], "rows": []}

    rows = _group_fields_into_rows(table_fields, row_gap=row_gap)
    col_ranges = _detect_column_x_ranges(rows, col_gap=col_gap)
    if not col_ranges:
        all_text = " ".join(str(field.get("inferText", "")).strip() for field in table_fields).strip()
        headers = [all_text] if all_text else []
        return {"headers": headers, "rows": []}

    grid: list[list[str]] = []
    for row_fields in rows:
        grid.append(_assign_fields_to_columns(row_fields, col_ranges))

    if not grid:
        return {"headers": [], "rows": []}

    width = max(len(row) for row in grid)
    headers = _unique_headers(grid[0], width)
    rows_dict: list[dict] = []
    for row in grid[1:]:
        padded = row + [""] * max(0, len(headers) - len(row))
        rows_dict.append(dict(zip(headers, padded[: len(headers)])))
    return {"headers": headers, "rows": rows_dict}


def _fields_to_lines(fields: list[dict]) -> str:
    lines: list[str] = []
    current: list[str] = []
    for field in sorted(fields, key=lambda value: (_field_center_y(value), _field_center_x(value))):
        text = str(field.get("inferText", "")).strip()
        if text:
            current.append(text)
        if field.get("lineBreak", False):
            if current:
                lines.append(" ".join(current))
                current = []
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _avg_confidence(fields: list[dict]) -> float | None:
    values: list[float] = []
    for field in fields:
        conf = field.get("inferConfidence")
        if isinstance(conf, (int, float)):
            values.append(float(conf))
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _fields_to_single_block(fields: list[dict]) -> list[LayoutBlock]:
    text = _fields_to_lines(fields)
    if not text.strip():
        return []
    all_vertices: list[dict] = []
    for field in fields:
        vertices = field.get("boundingPoly", {}).get("vertices", [])
        if isinstance(vertices, list):
            all_vertices.extend(vertices)
    bbox = list(_vertices_to_bbox(all_vertices))
    return [
        LayoutBlock(
            block_type="text",
            bbox=bbox,
            text=text,
            confidence=_avg_confidence(fields),
            source_method="ocr_clova",
            raw={},
        )
    ]


def _normalize_layout_region(region: Any) -> tuple[str, tuple[int, int, int, int]] | None:
    if isinstance(region, dict):
        block_type = str(region.get("block_type", region.get("type", "text")))
        bbox_raw = region.get("bbox")
    else:
        block_type = str(getattr(region, "block_type", "text"))
        bbox_raw = getattr(region, "bbox", None)

    if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) < 4:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(value))) for value in bbox_raw[:4]]
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None

    lowered = block_type.lower()
    if lowered == "table":
        normalized = "table"
    elif lowered in {"figure", "image"}:
        normalized = "figure"
    elif lowered == "title":
        normalized = "title"
    else:
        normalized = "text"
    return normalized, (x1, y1, x2, y2)


def clova_ocr_page(
    image,
    page_name: str = "page",
    layout_regions: list | None = None,
    timeout_sec: int | None = None,
) -> list[LayoutBlock]:
    """CLOVA OCR API로 단일 페이지를 처리하여 LayoutBlock 목록을 반환한다."""

    image_result = _request_clova(image, page_name=page_name, timeout_sec=timeout_sec)
    fields = image_result.get("fields", [])

    if layout_regions is None:
        return _fields_to_single_block(fields)

    blocks: list[LayoutBlock] = []
    used_indices: set[int] = set()

    for raw_region in layout_regions:
        normalized = _normalize_layout_region(raw_region)
        if normalized is None:
            continue
        block_type, bbox = normalized
        if block_type == "figure":
            continue

        matched_indices = _field_indices_in_bbox(fields, bbox)
        region_fields = [fields[index] for index in matched_indices]
        used_indices.update(matched_indices)

        if block_type == "table":
            table_json = reconstruct_table_from_fields(fields, bbox)
            text = _table_to_text(table_json)
            html = _table_json_to_html(table_json)
            if text.strip() or table_json.get("headers"):
                blocks.append(
                    LayoutBlock(
                        block_type="table",
                        bbox=list(bbox),
                        text=text,
                        html=html,
                        table_json=table_json,
                        confidence=None,
                        source_method="ocr_clova",
                        raw={},
                    )
                )
            continue

        text = _fields_to_lines(region_fields)
        if text.strip():
            blocks.append(
                LayoutBlock(
                    block_type=block_type,
                    bbox=list(bbox),
                    text=text,
                    confidence=_avg_confidence(region_fields),
                    source_method="ocr_clova",
                    raw={},
                )
            )

    remainder = [field for index, field in enumerate(fields) if index not in used_indices]
    remainder_text = _fields_to_lines(remainder)
    if remainder_text.strip():
        all_vertices: list[dict] = []
        for field in remainder:
            vertices = field.get("boundingPoly", {}).get("vertices", [])
            if isinstance(vertices, list):
                all_vertices.extend(vertices)
        blocks.append(
            LayoutBlock(
                block_type="text",
                bbox=list(_vertices_to_bbox(all_vertices)),
                text=remainder_text,
                confidence=_avg_confidence(remainder),
                source_method="ocr_clova",
                raw={"remainder": True},
            )
        )

    blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    return blocks if blocks else _fields_to_single_block(fields)

