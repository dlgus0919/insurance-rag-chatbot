"""Vision LLM-based cleanup for OCR table blocks."""

from __future__ import annotations

import base64
from dataclasses import replace
import io
import json
import logging
from typing import Any

from PIL import Image

from src.parser.clova_ocr import _table_json_to_html, _table_to_text
from src.parser.ocr_engine import LayoutBlock

LOGGER = logging.getLogger(__name__)
MAX_IMAGE_WIDTH = 800
VISION_PROMPT = """당신은 보험 약관 문서의 표를 검토하는 전문가입니다.
첨부 이미지는 표 영역 크롭입니다.

아래 JSON은 이 표의 OCR 추출 결과입니다.
다음 두 가지만 수정하세요:

1. 텍스트가 아닌 그림/도표/해부학적 이미지를 포함하는 셀:
   해당 셀의 텍스트를 "[그림]"으로 대체하세요.
   (셀 안에 그림이 있고 그 그림 위의 레이블 텍스트가 셀 값으로 잘못 인식된 경우)

2. 명백한 OCR 오탈자(문맥상 분명히 틀린 글자):
   올바른 텍스트로 수정하세요.

표 구조(행/열 수, headers 리스트, rows 키 이름)는 절대 변경하지 마세요.
JSON 형식만 반환하고 다른 설명은 출력하지 마세요.

현재 table_json:
{table_json}
"""


class TableVisionCleanerAuthError(RuntimeError):
    """Raised when the Vision API rejects authentication."""


def _crop_table_image(page_image: Image.Image, bbox: list[int]) -> Image.Image:
    width, height = page_image.size
    x1, y1, x2, y2 = [int(value) for value in bbox[:4]]
    x1 = max(0, min(width, x1))
    x2 = max(0, min(width, x2))
    y1 = max(0, min(height, y1))
    y2 = max(0, min(height, y2))
    if x2 <= x1 or y2 <= y1:
        return page_image.copy()
    return page_image.crop((x1, y1, x2, y2))


def _encode_image(image: Image.Image) -> str:
    image = image.convert("RGB")
    if image.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / image.width
        image = image.resize((MAX_IMAGE_WIDTH, max(1, int(image.height * ratio))))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _extract_json_object(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _same_table_shape(original: dict, candidate: dict) -> bool:
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
        if not isinstance(row, dict) or set(row.keys()) != expected_keys:
            return False
    return True


def _response_content(response: Any) -> str:
    choice = response.choices[0]
    message = choice.message
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(getattr(item, "text", "")))
        return "".join(parts)
    return str(content or "")


def _is_auth_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 401:
        return True
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 401


def _clean_single_table(block: LayoutBlock, page_image: Image.Image, client: Any, model: str) -> LayoutBlock:
    if not block.table_json:
        return block

    crop = _crop_table_image(page_image, block.bbox)
    image_b64 = _encode_image(crop)
    prompt = VISION_PROMPT.format(table_json=json.dumps(block.table_json, ensure_ascii=False, indent=2))

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
            raise TableVisionCleanerAuthError("OpenAI Vision API authentication failed") from exc
        LOGGER.warning("Vision table cleanup failed: %s", exc)
        return block

    parsed = _extract_json_object(_response_content(response))
    if parsed is None or not _same_table_shape(block.table_json, parsed):
        LOGGER.warning("Vision table cleanup returned invalid JSON shape")
        return block

    raw = dict(block.raw or {})
    raw["vision_cleaned"] = True
    return replace(
        block,
        table_json=parsed,
        text=_table_to_text(parsed),
        html=_table_json_to_html(parsed),
        raw=raw,
    )


def clean_table_blocks(
    blocks: list[LayoutBlock],
    page_image: Image.Image,
    client: Any,
    model: str = "gpt-4o-mini",
) -> list[LayoutBlock]:
    """Return LayoutBlocks with table_json cleaned by an OpenAI Vision model."""

    cleaned: list[LayoutBlock] = []
    for block in blocks:
        if block.block_type != "table":
            cleaned.append(block)
            continue
        cleaned.append(_clean_single_table(block, page_image, client, model))
    return cleaned
