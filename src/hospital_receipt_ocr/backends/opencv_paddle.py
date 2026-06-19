"""A-plan backend: OpenCV grid detection plus PaddleOCR text extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from ..models import OcrCell, OcrTable


@dataclass
class OcrTextBox:
    bbox: list[int]
    text: str
    confidence: float | None = None


class PaddleOcrAdapter:
    """Thin wrapper around PaddleOCR so tests can monkeypatch OCR boundaries."""

    def __init__(self) -> None:
        self._engine = None
        self.unavailable_reason: str = ""

    def _get_engine(self):  # noqa: ANN001
        if self._engine is None:
            try:
                from paddleocr import PaddleOCR
                self._engine = PaddleOCR(lang="korean", show_log=False, use_angle_cls=False)
            except KeyboardInterrupt:
                raise
            except BaseException as exc:  # pragma: no cover - environment dependent
                self.unavailable_reason = f"{exc.__class__.__name__}: {exc}"
                return None
        return self._engine

    def ocr_image(self, image: Image.Image) -> list[OcrTextBox]:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("numpy가 설치되어 있지 않습니다.") from exc

        arr = np.array(image.convert("RGB"))
        engine = self._get_engine()
        if engine is None:
            return []
        result = engine.ocr(arr, cls=False)
        return parse_paddle_result(result)


def parse_paddle_result(result: Any) -> list[OcrTextBox]:
    """Parse common PaddleOCR v2/v3 result shapes into text boxes."""

    boxes: list[OcrTextBox] = []
    if result is None:
        return boxes

    candidates = result
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], list):
        candidates = result[0]

    if not isinstance(candidates, list):
        return boxes

    for item in candidates:
        if isinstance(item, dict):
            text = str(item.get("text", "") or "")
            confidence = _to_float(item.get("confidence", item.get("score")))
            bbox = _bbox_from_points(item.get("bbox") or item.get("points") or item.get("text_region") or [])
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            bbox = _bbox_from_points(item[0])
            payload = item[1]
            text = ""
            confidence = None
            if isinstance(payload, (list, tuple)) and payload:
                text = str(payload[0] or "")
                if len(payload) > 1:
                    confidence = _to_float(payload[1])
            else:
                text = str(payload or "")
        else:
            continue
        if text.strip() and bbox:
            boxes.append(OcrTextBox(bbox=bbox, text=text.strip(), confidence=confidence))
    return boxes


def extract_tables_from_image(
    image: Image.Image,
    *,
    page_id: str,
    ocr: PaddleOcrAdapter | None = None,
    ocr_mode: str = "page_assign",
    min_cell_width: int = 18,
    min_cell_height: int = 12,
) -> list[OcrTable]:
    """Detect grid cells and populate OCR text.

    `page_assign` runs OCR once on the page and assigns text boxes to OpenCV
    cells. `crop` runs OCR per cell; it is mainly for small tests or targeted
    diagnostics because it is much slower on large hospital statements.
    """

    x_positions, y_positions = detect_grid_lines(image)
    cells = build_cells(
        page_id=page_id,
        x_positions=x_positions,
        y_positions=y_positions,
        min_cell_width=min_cell_width,
        min_cell_height=min_cell_height,
    )
    if not cells:
        return []

    ocr = ocr or PaddleOcrAdapter()
    if ocr_mode == "crop":
        cells = _ocr_cells_by_crop(image, cells, ocr)
    elif ocr_mode == "page_assign":
        cells = _ocr_cells_by_page_assignment(image, cells, ocr)
    else:
        raise ValueError(f"지원하지 않는 OCR 모드입니다: {ocr_mode}")

    table_bbox = [
        min(cell.bbox[0] for cell in cells),
        min(cell.bbox[1] for cell in cells),
        max(cell.bbox[2] for cell in cells),
        max(cell.bbox[3] for cell in cells),
    ]
    row_count = max(cell.row for cell in cells) + 1
    col_count = max(cell.col for cell in cells) + 1
    return [OcrTable(table_id=f"{page_id}_t001", page_id=page_id, bbox=table_bbox, rows=row_count, cols=col_count, cells=cells)]


def detect_grid_lines(image: Image.Image) -> tuple[list[int], list[int]]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return _detect_grid_lines_projection(image)

    arr = np.array(image.convert("L"))
    _, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    height, width = binary.shape

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(width // 35, 20), 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(height // 45, 20)))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel, iterations=1)

    y_positions = _projection_positions(horizontal, axis=1, min_run=max(width // 8, 30))
    x_positions = _projection_positions(vertical, axis=0, min_run=max(height // 10, 30))
    x_positions = _add_image_bounds(x_positions, width)
    y_positions = _add_image_bounds(y_positions, height)
    return x_positions, y_positions


def _detect_grid_lines_projection(image: Image.Image) -> tuple[list[int], list[int]]:
    """Fallback grid detector when cv2 cannot be imported in the runtime."""

    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("numpy가 필요합니다.") from exc

    arr = np.array(image.convert("L"))
    height, width = arr.shape
    dark = arr < 170
    horizontal_mask = (dark.sum(axis=1) >= max(width // 3, 30)).astype("uint8")[:, None]
    vertical_mask = (dark.sum(axis=0) >= max(height // 5, 30)).astype("uint8")[None, :]
    horizontal = horizontal_mask.repeat(width, axis=1)
    vertical = vertical_mask.repeat(height, axis=0)
    y_positions = _projection_positions(horizontal, axis=1, min_run=max(width // 8, 30))
    x_positions = _projection_positions(vertical, axis=0, min_run=max(height // 10, 30))
    return _add_image_bounds(x_positions, width), _add_image_bounds(y_positions, height)


def build_cells(
    *,
    page_id: str,
    x_positions: list[int],
    y_positions: list[int],
    min_cell_width: int = 18,
    min_cell_height: int = 12,
) -> list[OcrCell]:
    cells: list[OcrCell] = []
    for row, (y1, y2) in enumerate(zip(y_positions, y_positions[1:])):
        if y2 - y1 < min_cell_height:
            continue
        for col, (x1, x2) in enumerate(zip(x_positions, x_positions[1:])):
            if x2 - x1 < min_cell_width:
                continue
            cell_id = f"{page_id}_r{row:03d}_c{col:03d}"
            cells.append(OcrCell(cell_id=cell_id, page_id=page_id, row=row, col=col, bbox=[x1, y1, x2, y2]))
    return cells


def save_cell_artifact(path: Path, table: OcrTable) -> None:
    from json import dumps
    from ..models import dataclass_to_dict

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(dataclass_to_dict(table), ensure_ascii=False, indent=2), encoding="utf-8")


def _ocr_cells_by_page_assignment(image: Image.Image, cells: list[OcrCell], ocr: PaddleOcrAdapter) -> list[OcrCell]:
    text_boxes = ocr.ocr_image(image)
    assignments: dict[str, list[OcrTextBox]] = {cell.cell_id: [] for cell in cells}
    for box in text_boxes:
        cx = (box.bbox[0] + box.bbox[2]) / 2
        cy = (box.bbox[1] + box.bbox[3]) / 2
        for cell in cells:
            x1, y1, x2, y2 = cell.bbox
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                assignments[cell.cell_id].append(box)
                break

    updated: list[OcrCell] = []
    for cell in cells:
        boxes = sorted(assignments[cell.cell_id], key=lambda b: (b.bbox[1], b.bbox[0]))
        if boxes:
            cell.text = " ".join(box.text for box in boxes).strip()
            confidences = [box.confidence for box in boxes if box.confidence is not None]
            cell.confidence = sum(confidences) / len(confidences) if confidences else None
            cell.raw["assigned_boxes"] = [box.__dict__ for box in boxes]
        updated.append(cell)
    return updated


def _ocr_cells_by_crop(image: Image.Image, cells: list[OcrCell], ocr: PaddleOcrAdapter) -> list[OcrCell]:
    updated: list[OcrCell] = []
    for cell in cells:
        crop = image.crop(tuple(cell.bbox))
        boxes = ocr.ocr_image(crop)
        if boxes:
            cell.text = " ".join(box.text for box in boxes).strip()
            confidences = [box.confidence for box in boxes if box.confidence is not None]
            cell.confidence = sum(confidences) / len(confidences) if confidences else None
            cell.raw["crop_boxes"] = [box.__dict__ for box in boxes]
        updated.append(cell)
    return updated


def _projection_positions(mask, *, axis: int, min_run: int) -> list[int]:  # noqa: ANN001
    import numpy as np

    projection = np.sum(mask > 0, axis=axis)
    threshold = max(min_run, int(projection.max() * 0.35)) if projection.size else min_run
    indices = [int(i) for i, value in enumerate(projection) if value >= threshold]
    if not indices:
        return []
    clusters: list[list[int]] = [[indices[0]]]
    for index in indices[1:]:
        if index - clusters[-1][-1] <= 3:
            clusters[-1].append(index)
        else:
            clusters.append([index])
    return [int(round(sum(cluster) / len(cluster))) for cluster in clusters]


def _add_image_bounds(positions: list[int], limit: int) -> list[int]:
    merged = sorted({max(0, min(limit, int(pos))) for pos in positions})
    if not merged:
        return []
    if merged[0] > 8:
        merged.insert(0, 0)
    if limit - merged[-1] > 8:
        merged.append(limit)
    return merged


def _bbox_from_points(points: Any) -> list[int]:
    if not points:
        return []
    if isinstance(points, (list, tuple)) and len(points) == 4 and all(not isinstance(v, (list, tuple)) for v in points):
        return [int(round(float(v))) for v in points]
    xs: list[float] = []
    ys: list[float] = []
    for point in points:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
    if not xs or not ys:
        return []
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
