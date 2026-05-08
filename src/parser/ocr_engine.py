"""PP-Structure OCR 엔진과 EasyOCR 폴백 어댑터."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LayoutBlock:
    """PP-Structure 또는 폴백 OCR에서 감지한 레이아웃 블록 하나."""

    block_type: str
    bbox: list[int]
    text: str
    html: str | None = None
    confidence: float = 1.0
    raw: dict = field(default_factory=dict)


_ppstructure_instance = None
_easyocr_reader = None
_ppstructure_lang = None


def _clean_cell_text(text: str) -> str:
    return " ".join(str(text).split())


def _table_html_to_text(html: str) -> str:
    """HTML 표를 파이프 구분 텍스트로 직렬화한다."""

    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("beautifulsoup4가 설치되어 있지 않습니다. requirements-ocr.txt를 설치하세요.") from exc

    soup = BeautifulSoup(html, "lxml")
    rows: list[str] = []
    for tr in soup.find_all("tr"):
        cells = [_clean_cell_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _unique_headers(headers: list[str], width: int) -> list[str]:
    normalized: list[str] = []
    seen: dict[str, int] = {}
    for index in range(width):
        header = headers[index] if index < len(headers) else ""
        header = header or f"col_{index + 1}"
        count = seen.get(header, 0)
        seen[header] = count + 1
        normalized.append(header if count == 0 else f"{header}_{count + 1}")
    return normalized


def _table_html_to_json(html: str) -> dict:
    """HTML 표를 headers+rows JSON 구조로 변환한다."""

    if not html:
        return {"headers": [], "rows": []}
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("beautifulsoup4가 설치되어 있지 않습니다. requirements-ocr.txt를 설치하세요.") from exc

    soup = BeautifulSoup(html, "lxml")
    parsed_rows: list[list[str]] = []
    for tr in soup.find_all("tr"):
        cells = [_clean_cell_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            parsed_rows.append(cells)

    if not parsed_rows:
        return {"headers": [], "rows": []}

    width = max(len(row) for row in parsed_rows)
    headers = _unique_headers(parsed_rows[0], width)
    rows: list[dict | list[str]] = []
    for cells in parsed_rows[1:]:
        padded = cells + [""] * max(0, len(headers) - len(cells))
        rows.append(dict(zip(headers, padded[: len(headers)])))
    return {"headers": headers, "rows": rows}


def _bbox_from_region(region: dict) -> list[int]:
    bbox = region.get("bbox") or region.get("text_region") or [0, 0, 0, 0]
    if len(bbox) == 4 and all(not isinstance(value, (list, tuple)) for value in bbox):
        return [int(round(float(value))) for value in bbox]
    xs = [float(point[0]) for point in bbox if len(point) >= 2]
    ys = [float(point[1]) for point in bbox if len(point) >= 2]
    if not xs or not ys:
        return [0, 0, 0, 0]
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def _normalize_block_type(block_type: str) -> str:
    lowered = (block_type or "text").lower()
    if lowered in {"table"}:
        return "table"
    if lowered in {"figure", "image"}:
        return "figure"
    if lowered in {"title"}:
        return "title"
    return "text"


def _parse_text_result(res: Any) -> tuple[str, float]:
    if isinstance(res, list):
        texts: list[str] = []
        confidences: list[float] = []
        for item in res:
            text = ""
            confidence = 1.0
            if isinstance(item, dict):
                text = str(item.get("text", ""))
                confidence = float(item.get("confidence", item.get("score", 1.0)) or 0.0)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                payload = item[1]
                if isinstance(payload, (list, tuple)) and payload:
                    text = str(payload[0])
                    if len(payload) > 1:
                        confidence = float(payload[1] or 0.0)
                else:
                    text = str(payload)
            if text and confidence >= 0.5:
                texts.append(text)
                confidences.append(confidence)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return " ".join(texts), float(avg_conf)
    if isinstance(res, dict):
        text = str(res.get("text", res.get("html", "")))
        confidence = float(res.get("confidence", res.get("score", 1.0)) or 0.0)
        return text, confidence
    return str(res or ""), 1.0


def _region_to_block(region: dict) -> LayoutBlock:
    """PP-Structure region dict를 LayoutBlock으로 변환한다."""

    block_type = _normalize_block_type(str(region.get("type", "text")))
    bbox = _bbox_from_region(region)
    res = region.get("res", {})

    if block_type == "table":
        html = ""
        confidence = float(region.get("score", 1.0) or 0.0)
        raw = {}
        if isinstance(res, dict):
            html = str(res.get("html", ""))
            confidence = float(res.get("score", res.get("confidence", confidence)) or 0.0)
            raw = {"cell_bbox": res.get("cell_bbox", [])}
        text = _table_html_to_text(html)
        return LayoutBlock("table", bbox, text, html=html, confidence=confidence, raw=raw)

    if block_type == "figure":
        return LayoutBlock("figure", bbox, "", confidence=float(region.get("score", 1.0) or 0.0), raw={})

    text, confidence = _parse_text_result(res)
    return LayoutBlock(block_type, bbox, text, confidence=confidence, raw={})


def _get_ppstructure_engine():
    """PPStructure 엔진을 지연 초기화한다."""

    global _ppstructure_instance, _ppstructure_lang
    if _ppstructure_instance is None:
        try:
            from paddleocr import PPStructure
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise RuntimeError("paddleocr PPStructure를 import할 수 없습니다. requirements-ocr.txt를 설치하세요.") from exc

        errors: list[str] = []
        for lang in ("korean", "ch"):
            try:
                _ppstructure_instance = PPStructure(
                    table=True,
                    ocr=True,
                    lang=lang,
                    show_log=False,
                    image_orientation=False,
                )
                _ppstructure_lang = lang
                break
            except KeyboardInterrupt:
                raise
            except BaseException as exc:  # pragma: no cover - PaddleOCR가 SystemExit을 던질 수 있다.
                errors.append(f"{lang}: {exc.__class__.__name__}: {exc}")
        if _ppstructure_instance is None:
            raise RuntimeError("PPStructure 초기화 실패: " + " | ".join(errors))
    return _ppstructure_instance


def run_ppstructure(image) -> list[LayoutBlock]:
    """PP-Structure로 레이아웃 분석과 영역별 OCR을 실행한다."""

    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("numpy가 설치되어 있지 않습니다.") from exc

    engine = _get_ppstructure_engine()
    result = engine(np.array(image))
    blocks = [_region_to_block(region) for region in result]
    blocks = [block for block in blocks if block.block_type == "figure" or block.text or block.html]
    blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    return blocks


def _get_easyocr_reader():
    """EasyOCR reader를 지연 초기화한다."""

    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise RuntimeError("easyocr가 설치되어 있지 않습니다. requirements-ocr.txt를 설치하세요.") from exc
        _easyocr_reader = easyocr.Reader(["ko", "en"], gpu=False)
    return _easyocr_reader


def run_easyocr_fallback(image) -> list[LayoutBlock]:
    """PP-Structure 신뢰도가 낮거나 실행 실패 시 EasyOCR로 텍스트 블록을 추출한다."""

    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("numpy가 설치되어 있지 않습니다.") from exc

    reader = _get_easyocr_reader()
    result = reader.readtext(np.array(image), detail=1, paragraph=False)
    blocks: list[LayoutBlock] = []
    for bbox_pts, text, confidence in result:
        xs = [point[0] for point in bbox_pts]
        ys = [point[1] for point in bbox_pts]
        bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
        blocks.append(LayoutBlock("text", bbox, str(text), confidence=float(confidence or 0.0)))
    blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    return blocks


def should_use_easyocr_fallback(blocks: list[LayoutBlock], threshold: float) -> bool:
    """PP-Structure 결과가 비었거나 평균 신뢰도가 낮으면 폴백한다."""

    if not blocks:
        return True
    confidence_blocks = [block for block in blocks if block.block_type in {"title", "text", "table"}]
    if not confidence_blocks:
        return False
    avg_conf = sum(block.confidence for block in confidence_blocks) / len(confidence_blocks)
    return avg_conf < threshold
