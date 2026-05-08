"""CLOVA OCR API 클라이언트."""

from __future__ import annotations

import io
import json
import os
import uuid

import requests

from src.parser.ocr_engine import LayoutBlock

_REQUEST_TIMEOUT_SEC = 30


class ClovaOcrError(RuntimeError):
    """CLOVA OCR 호출/파싱 실패."""


def _vertices_to_bbox(vertices: list[dict]) -> tuple[int, int, int, int]:
    """boundingPoly vertices를 xyxy bbox로 변환."""

    if not vertices:
        return (0, 0, 0, 0)
    xs = [int(v.get("x", 0)) for v in vertices]
    ys = [int(v.get("y", 0)) for v in vertices]
    return (min(xs), min(ys), max(xs), max(ys))


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
            value = str(word.get("text", "")).strip()
            if value:
                words.append(value)
    return " ".join(words)


def _table_to_json(table: dict) -> dict:
    """CLOVA table 응답을 headers/rows 구조로 변환."""

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
    parts: list[str] = []
    headers = [str(value) for value in table_json.get("headers", [])]
    if headers:
        parts.append(" | ".join(headers))
    for row in table_json.get("rows", []):
        if isinstance(row, dict):
            values = [str(row.get(header, "")) for header in headers]
        else:
            values = [str(value) for value in row]
        parts.append(" | ".join(values))
    return "\n".join(parts)


def _load_clova_env() -> tuple[str, str]:
    url = os.getenv("CLOVA_OCR_URL", "").strip()
    secret = os.getenv("CLOVA_OCR_SECRET", "").strip()
    if not url or not secret:
        raise ClovaOcrError("CLOVA_OCR_URL 또는 CLOVA_OCR_SECRET 환경변수가 설정되지 않았습니다.")
    return url, secret


def _build_lines_from_fields(fields: list[dict]) -> tuple[str, float | None, list[int]]:
    lines: list[str] = []
    current: list[str] = []
    confidences: list[float] = []
    all_vertices: list[dict] = []

    for field in fields:
        text = str(field.get("inferText", "")).strip()
        if text:
            current.append(text)
        conf = field.get("inferConfidence")
        if isinstance(conf, (int, float)):
            confidences.append(float(conf))
        vertices = field.get("boundingPoly", {}).get("vertices", [])
        if isinstance(vertices, list):
            all_vertices.extend(vertices)
        if field.get("lineBreak", False):
            if current:
                lines.append(" ".join(current))
                current = []
    if current:
        lines.append(" ".join(current))

    avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else None
    bbox = list(_vertices_to_bbox(all_vertices))
    return "\n".join(lines), avg_conf, bbox


def clova_ocr_page(image, page_name: str = "page") -> list[LayoutBlock]:
    """CLOVA OCR API로 단일 페이지를 OCR 처리한다."""

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
    try:
        response = requests.post(
            url,
            headers={"X-OCR-SECRET": secret},
            files={
                "message": (None, message, "application/json"),
                "file": (f"{page_name}.jpg", buffer, "image/jpeg"),
            },
            timeout=_REQUEST_TIMEOUT_SEC,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ClovaOcrError(f"CLOVA OCR API 요청 실패: {exc}") from exc

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

    blocks: list[LayoutBlock] = []

    for index, table in enumerate(image_result.get("tables", [])):
        cells = table.get("cells", [])
        if not cells:
            continue
        all_vertices: list[dict] = []
        for cell in cells:
            vertices = cell.get("boundingPoly", {}).get("vertices", [])
            if isinstance(vertices, list):
                all_vertices.extend(vertices)
        bbox = list(_vertices_to_bbox(all_vertices))
        table_json = _table_to_json(table)
        table_text = _table_to_text(table_json)
        blocks.append(
            LayoutBlock(
                block_type="table",
                bbox=bbox,
                text=table_text,
                table_json=table_json,
                confidence=None,
                source_method="ocr_clova",
                raw={"table_index": index},
            )
        )

    fields = image_result.get("fields", [])
    if fields:
        text, confidence, bbox = _build_lines_from_fields(fields)
        if text:
            blocks.append(
                LayoutBlock(
                    block_type="text",
                    bbox=bbox,
                    text=text,
                    confidence=confidence,
                    source_method="ocr_clova",
                    raw={},
                )
            )

    blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    return blocks

