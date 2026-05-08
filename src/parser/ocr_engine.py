"""PP-Structure two-pass OCR 엔진과 EasyOCR 폴백 어댑터."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LayoutBlock:
    """OCR 결과 레이아웃 블록."""

    block_type: str
    bbox: list[int]
    text: str
    html: str | None = None
    table_json: dict | None = None
    confidence: float | None = 1.0
    source_method: str = "ocr_ppstructure"
    raw: dict = field(default_factory=dict)


_structure_engine = None
_table_structure_engine = None
_korean_ocr_engine = None
_easyocr_reader = None


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
    rows: list[dict] = []
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
    if lowered == "table":
        return "table"
    if lowered in {"figure", "image"}:
        return "figure"
    if lowered == "title":
        return "title"
    return "text"


def _parse_text_result(res: Any) -> tuple[str, float]:
    """PP-Structure text 결과를 문자열 + 평균 confidence로 변환한다."""

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
    """기존 single-pass 테스트 호환용 region -> LayoutBlock 변환."""

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
        return LayoutBlock(
            "table",
            bbox,
            text,
            html=html,
            table_json=_table_html_to_json(html),
            confidence=confidence,
            source_method="ocr_ppstructure",
            raw=raw,
        )

    if block_type == "figure":
        return LayoutBlock(
            "figure",
            bbox,
            "",
            confidence=float(region.get("score", 1.0) or 0.0),
            source_method="ocr_ppstructure",
            raw={},
        )

    text, confidence = _parse_text_result(res)
    return LayoutBlock(
        block_type,
        bbox,
        text,
        confidence=confidence,
        source_method="ocr_ppstructure",
        raw={},
    )


def _get_ppstructure_with_fallback(**kwargs):
    try:
        from paddleocr import PPStructure
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("paddleocr PPStructure를 import할 수 없습니다. requirements-ocr.txt를 설치하세요.") from exc

    errors: list[str] = []
    for candidate in (
        kwargs,
        {k: v for k, v in kwargs.items() if k != "ocr"},
        {k: v for k, v in kwargs.items() if k not in {"ocr", "image_orientation"}},
    ):
        try:
            return PPStructure(**candidate)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # pragma: no cover - PaddleOCR 내부 구현 의존
            errors.append(f"{exc.__class__.__name__}: {exc}")
    raise RuntimeError("PPStructure 초기화 실패: " + " | ".join(errors))


def _get_structure_engine():
    """레이아웃 bbox 탐지용 PP-Structure 엔진."""

    global _structure_engine
    if _structure_engine is None:
        _structure_engine = _get_ppstructure_with_fallback(
            table=True,
            ocr=False,
            lang="ch",
            show_log=False,
            image_orientation=False,
        )
    return _structure_engine


def _get_table_structure_engine():
    """표 셀 bbox 탐지용 PP-Structure 엔진."""

    global _table_structure_engine
    if _table_structure_engine is None:
        _table_structure_engine = _get_ppstructure_with_fallback(
            table=True,
            ocr=False,
            lang="ch",
            show_log=False,
            image_orientation=False,
        )
    return _table_structure_engine


def _get_korean_ocr():
    """한국어 OCR 엔진 싱글턴."""

    global _korean_ocr_engine
    if _korean_ocr_engine is None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise RuntimeError("paddleocr PaddleOCR를 import할 수 없습니다. requirements-ocr.txt를 설치하세요.") from exc
        _korean_ocr_engine = PaddleOCR(lang="korean", show_log=False)
    return _korean_ocr_engine


def _flatten_ocr_result(ocr_result: Any) -> tuple[str, float]:
    """PaddleOCR 결과를 줄바꿈 텍스트 + 평균 confidence로 평탄화한다."""

    lines: list[str] = []
    confidences: list[float] = []
    if isinstance(ocr_result, list):
        for page in ocr_result:
            if not isinstance(page, list):
                continue
            for line in page:
                if not line or len(line) < 2:
                    continue
                payload = line[1]
                if isinstance(payload, (list, tuple)) and payload:
                    text = str(payload[0]).strip()
                    if text:
                        lines.append(text)
                    if len(payload) > 1:
                        try:
                            confidences.append(float(payload[1]))
                        except (TypeError, ValueError):
                            pass
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return "\n".join(lines), round(avg_conf, 3)


def _poly_or_bbox_to_xyxy(cell_bbox: Any) -> tuple[int, int, int, int] | None:
    """PP-Structure 셀 bbox(4점/4숫자/8숫자)를 xyxy로 변환."""

    if not isinstance(cell_bbox, (list, tuple)):
        return None
    if len(cell_bbox) == 4 and all(not isinstance(value, (list, tuple)) for value in cell_bbox):
        try:
            x1, y1, x2, y2 = [int(round(float(v))) for v in cell_bbox]
        except (TypeError, ValueError):
            return None
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2
    if len(cell_bbox) >= 8 and all(not isinstance(value, (list, tuple)) for value in cell_bbox):
        try:
            xs = [float(cell_bbox[i]) for i in range(0, len(cell_bbox), 2)]
            ys = [float(cell_bbox[i]) for i in range(1, len(cell_bbox), 2)]
        except (TypeError, ValueError):
            return None
        if not xs or not ys:
            return None
        x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2
    if all(isinstance(value, (list, tuple)) and len(value) >= 2 for value in cell_bbox):
        try:
            xs = [float(point[0]) for point in cell_bbox]
            ys = [float(point[1]) for point in cell_bbox]
        except (TypeError, ValueError):
            return None
        x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2
    return None


def _extract_cell_bboxes(table_region: dict) -> list[tuple[int, int, int, int]]:
    res = table_region.get("res", {})
    raw_cells = res.get("cell_bbox", []) if isinstance(res, dict) else []
    cells: list[tuple[int, int, int, int]] = []
    for cell in raw_cells:
        normalized = _poly_or_bbox_to_xyxy(cell)
        if normalized is not None:
            cells.append(normalized)
    return cells


def _cluster_rows(cells: list[tuple[int, int, int, int]], y_threshold: int = 20) -> list[list[tuple[int, int, int, int]]]:
    if not cells:
        return []
    sorted_cells = sorted(cells, key=lambda item: ((item[1] + item[3]) / 2.0, item[0]))
    rows: list[list[tuple[int, int, int, int]]] = []
    centers: list[float] = []
    for cell in sorted_cells:
        center = (cell[1] + cell[3]) / 2.0
        if not rows:
            rows.append([cell])
            centers.append(center)
            continue
        if abs(center - centers[-1]) <= y_threshold:
            rows[-1].append(cell)
            centers[-1] = (centers[-1] * (len(rows[-1]) - 1) + center) / len(rows[-1])
        else:
            rows.append([cell])
            centers.append(center)
    for row in rows:
        row.sort(key=lambda item: item[0])
    return rows


def _json_to_table_html(table_json: dict) -> str:
    headers = [str(value) for value in table_json.get("headers", [])]
    rows = table_json.get("rows", [])
    lines = ["<table>"]
    if headers:
        lines.append("<tr>" + "".join(f"<td>{header}</td>" for header in headers) + "</tr>")
    for row in rows:
        if isinstance(row, dict):
            values = [str(row.get(header, "")) for header in headers]
        else:
            values = [str(value) for value in row]
        lines.append("<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>")
    lines.append("</table>")
    return "".join(lines)


def _extract_table_twopass(region_array: Any, korean_ocr, offset: tuple[int, int] = (0, 0)) -> tuple[str, dict, dict]:
    """표 영역의 셀 bbox에 Korean OCR을 적용해 HTML/JSON을 재구성한다."""

    table_engine = _get_table_structure_engine()
    table_results = table_engine(region_array)
    table_region = next(
        (region for region in table_results if _normalize_block_type(str(region.get("type", ""))) == "table"),
        {},
    )
    cell_bboxes = _extract_cell_bboxes(table_region)
    if not cell_bboxes:
        text, _ = _flatten_ocr_result(korean_ocr.ocr(region_array, cls=False))
        fallback_text = _clean_cell_text(text)
        table_json = {"headers": [fallback_text] if fallback_text else [], "rows": []}
        html = _json_to_table_html(table_json)
        raw = {"cell_bbox": [], "offset": {"x": offset[0], "y": offset[1]}}
        return html, table_json, raw

    region_h, region_w = int(region_array.shape[0]), int(region_array.shape[1])
    normalized_cells: list[tuple[int, int, int, int]] = []
    for x1, y1, x2, y2 in cell_bboxes:
        cx1 = max(0, min(region_w, int(x1)))
        cx2 = max(0, min(region_w, int(x2)))
        cy1 = max(0, min(region_h, int(y1)))
        cy2 = max(0, min(region_h, int(y2)))
        if cx2 <= cx1 or cy2 <= cy1:
            continue
        normalized_cells.append((cx1, cy1, cx2, cy2))
    if not normalized_cells:
        text, _ = _flatten_ocr_result(korean_ocr.ocr(region_array, cls=False))
        fallback_text = _clean_cell_text(text)
        table_json = {"headers": [fallback_text] if fallback_text else [], "rows": []}
        html = _json_to_table_html(table_json)
        raw = {"cell_bbox": [], "offset": {"x": offset[0], "y": offset[1]}}
        return html, table_json, raw

    rows = _cluster_rows(normalized_cells)
    row_texts: list[list[str]] = []
    cell_bbox_out: list[list[int]] = []
    confidences: list[float] = []

    for row in rows:
        current_row: list[str] = []
        for x1, y1, x2, y2 in row:
            crop = region_array[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            text, conf = _flatten_ocr_result(korean_ocr.ocr(crop, cls=False))
            current_row.append(_clean_cell_text(text))
            cell_bbox_out.append([x1 + offset[0], y1 + offset[1], x2 + offset[0], y2 + offset[1]])
            if conf > 0:
                confidences.append(conf)
        row_texts.append(current_row)

    if not row_texts:
        table_json = {"headers": [], "rows": []}
        html = _json_to_table_html(table_json)
        raw = {"cell_bbox": cell_bbox_out, "offset": {"x": offset[0], "y": offset[1]}}
        return html, table_json, raw

    width = max(len(row) for row in row_texts)
    headers = _unique_headers(row_texts[0], width)
    rows_json: list[dict] = []
    for row in row_texts[1:]:
        padded = row + [""] * max(0, len(headers) - len(row))
        rows_json.append(dict(zip(headers, padded[: len(headers)])))
    table_json = {"headers": headers, "rows": rows_json}
    if confidences:
        table_json["avg_confidence"] = round(sum(confidences) / len(confidences), 3)
    html = _json_to_table_html(table_json)
    raw = {"cell_bbox": cell_bbox_out, "offset": {"x": offset[0], "y": offset[1]}}
    return html, table_json, raw


def ocr_page(image) -> list[LayoutBlock]:
    """PP-Structure bbox + PaddleOCR Korean two-pass OCR 실행."""

    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("numpy가 설치되어 있지 않습니다.") from exc

    structure_engine = _get_structure_engine()
    korean_ocr = _get_korean_ocr()
    structure_results = structure_engine(np.array(image))
    blocks: list[LayoutBlock] = []

    for region in structure_results:
        block_type = _normalize_block_type(str(region.get("type", "text")))
        bbox = _bbox_from_region(region)
        x1, y1, x2, y2 = bbox
        if x2 <= x1 or y2 <= y1:
            continue
        region_img = image.crop((x1, y1, x2, y2))
        region_array = np.array(region_img)

        if block_type == "table":
            html, table_json, raw = _extract_table_twopass(region_array, korean_ocr, (x1, y1))
            blocks.append(
                LayoutBlock(
                    block_type="table",
                    bbox=bbox,
                    text=_table_html_to_text(html),
                    html=html,
                    table_json=table_json,
                    confidence=table_json.get("avg_confidence"),
                    source_method="ocr_ppstructure_twopass",
                    raw=raw,
                )
            )
            continue

        if block_type == "figure":
            blocks.append(
                LayoutBlock(
                    block_type="figure",
                    bbox=bbox,
                    text="",
                    confidence=float(region.get("score", 1.0) or 0.0),
                    source_method="ocr_ppstructure_twopass",
                    raw={},
                )
            )
            continue

        text, confidence = _flatten_ocr_result(korean_ocr.ocr(region_array, cls=False))
        blocks.append(
            LayoutBlock(
                block_type=block_type,
                bbox=bbox,
                text=text,
                confidence=confidence,
                source_method="ocr_ppstructure_twopass",
                raw={},
            )
        )

    blocks = [block for block in blocks if block.block_type == "figure" or block.text or block.html]
    blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    return blocks


def run_ppstructure(image) -> list[LayoutBlock]:
    """기본 OCR 엔트리포인트. two-pass 결과를 반환한다."""

    return ocr_page(image)


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
    """PP-Structure 결과가 없거나 신뢰도가 낮을 때 EasyOCR 폴백 결과를 반환한다."""

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
        blocks.append(
            LayoutBlock(
                block_type="text",
                bbox=bbox,
                text=str(text),
                confidence=float(confidence or 0.0),
                source_method="ocr_easyocr",
                raw={},
            )
        )
    blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    return blocks


def should_use_easyocr_fallback(blocks: list[LayoutBlock], threshold: float) -> bool:
    """PP-Structure 결과가 비었거나 평균 신뢰도가 낮으면 폴백한다."""

    if not blocks:
        return True
    confidence_blocks = [block for block in blocks if block.block_type in {"title", "text", "table"}]
    if not confidence_blocks:
        return False
    values = [float(block.confidence) for block in confidence_blocks if block.confidence is not None]
    if not values:
        return False
    avg_conf = sum(values) / len(values)
    return avg_conf < threshold
