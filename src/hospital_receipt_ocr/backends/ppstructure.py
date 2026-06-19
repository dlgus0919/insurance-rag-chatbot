"""B-plan backend: PaddleOCR PP-Structure table extraction."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from ..models import OcrCell, OcrTable
from .opencv_paddle import OcrTextBox, PaddleOcrAdapter
from .table_html import html_table_to_ocr_table


@dataclass
class PPStructureAdapter:
    """Small table-structure wrapper kept separate from batch OCR ingestion code."""

    _engine: Any | None = None
    unavailable_reason: str = ""

    def _get_engine(self):  # noqa: ANN001
        if self._engine is not None:
            return self._engine
        try:
            import paddleocr.paddleocr as paddleocr_module
            from paddleocr.paddleocr import BASE_DIR, confirm_model_dir_url, get_model_config, maybe_download, parse_args
            from ppstructure.table.predict_table import TableSystem
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # pragma: no cover - environment dependent
            self.unavailable_reason = f"{exc.__class__.__name__}: {exc}"
            return None

        try:
            params = parse_args(mMain=False)
            params.__dict__.update(
                show_log=False,
                lang="ch",
                layout=False,
                table=True,
                formula=False,
                ocr=False,
                recovery=False,
                use_gpu=False,
            )
            _prepare_table_system_model_dirs(params, paddleocr_module=paddleocr_module, base_dir=BASE_DIR, get_model_config=get_model_config, confirm_model_dir_url=confirm_model_dir_url, maybe_download=maybe_download)
            self._engine = TableSystem(params)
            return self._engine
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # pragma: no cover - PaddleOCR version dependent
            self.unavailable_reason = f"TableSystem 초기화 실패: {exc.__class__.__name__}: {exc}"
            return None

    def structure_image(self, image: Image.Image) -> list[Any]:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - environment dependent
            self.unavailable_reason = f"numpy unavailable: {exc}"
            return []

        engine = self._get_engine()
        if engine is None:
            return []
        arr = np.array(image.convert("RGB"))
        try:
            result, _time_dict = engine(arr, return_ocr_result_in_table=True)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # pragma: no cover - PaddleOCR version dependent
            self.unavailable_reason = f"TableSystem 실행 실패: {exc.__class__.__name__}: {exc}"
            return []
        if isinstance(result, dict):
            return [{"type": "table", "bbox": [0, 0, image.width, image.height], "res": result}]
        if isinstance(result, list):
            return result
        return []


def _prepare_table_system_model_dirs(params: Any, *, paddleocr_module: Any, base_dir: str, get_model_config: Any, confirm_model_dir_url: Any, maybe_download: Any) -> None:
    """Populate only det/rec/table model dirs required by TableSystem."""

    ocr_version = getattr(params, "ocr_version", "PP-OCRv4")
    structure_version = getattr(params, "structure_version", "PP-StructureV2")
    det_model_config = get_model_config("OCR", ocr_version, "det", "ch")
    rec_model_config = get_model_config("OCR", ocr_version, "rec", "ch")
    table_model_config = get_model_config("STRUCTURE", structure_version, "table", "ch")

    params.det_model_dir, det_url = confirm_model_dir_url(
        params.det_model_dir,
        os.path.join(base_dir, "whl", "det", "ch"),
        det_model_config["url"],
    )
    params.rec_model_dir, rec_url = confirm_model_dir_url(
        params.rec_model_dir,
        os.path.join(base_dir, "whl", "rec", "ch"),
        rec_model_config["url"],
    )
    params.table_model_dir, table_url = confirm_model_dir_url(
        params.table_model_dir,
        os.path.join(base_dir, "whl", "table"),
        table_model_config["url"],
    )
    if not getattr(params, "use_onnx", False):
        maybe_download(params.det_model_dir, det_url)
        maybe_download(params.rec_model_dir, rec_url)
        maybe_download(params.table_model_dir, table_url)

    dict_base = Path(paddleocr_module.__file__).parent
    if params.rec_char_dict_path is None:
        params.rec_char_dict_path = str(dict_base / rec_model_config["dict_path"])
    if params.table_char_dict_path is None:
        params.table_char_dict_path = str(dict_base / table_model_config["dict_path"])


def extract_tables_from_image(
    image: Image.Image,
    *,
    page_id: str,
    ppstructure: PPStructureAdapter | None = None,
    text_ocr: PaddleOcrAdapter | None = None,
) -> list[OcrTable]:
    adapter = ppstructure or PPStructureAdapter()
    result = adapter.structure_image(image)
    tables: list[OcrTable] = []
    for index, region in enumerate(result, start=1):
        table = _table_from_cell_bboxes(
            image,
            page_id=page_id,
            table_id=f"{page_id}_pp_t{index:03d}",
            region=region,
            text_ocr=text_ocr,
        )
        if table is not None:
            tables.append(table)
            continue
        html = _extract_table_html(region)
        if not html:
            continue
        table = html_table_to_ocr_table(
            page_id=page_id,
            table_id=f"{page_id}_pp_t{index:03d}",
            bbox=_extract_bbox(region, image),
            html=html,
            source_method="ppstructure",
            raw=_raw_region_summary(region),
        )
        if table is not None:
            tables.append(table)
    return tables


def _table_from_cell_bboxes(
    image: Image.Image,
    *,
    page_id: str,
    table_id: str,
    region: Any,
    text_ocr: PaddleOcrAdapter | None,
) -> OcrTable | None:
    if not isinstance(region, dict):
        return None
    res = region.get("res")
    if not isinstance(res, dict):
        return None
    boxes = [_bbox_from_value(box) for box in res.get("cell_bbox", [])]
    boxes = [box for box in boxes if box]
    if not boxes:
        return None

    cells = _cells_from_bboxes(page_id=page_id, boxes=boxes)
    text_boxes = (text_ocr or PaddleOcrAdapter()).ocr_image(image)
    _assign_text_boxes(cells, text_boxes)

    table_bbox = [
        min(cell.bbox[0] for cell in cells),
        min(cell.bbox[1] for cell in cells),
        max(cell.bbox[2] for cell in cells),
        max(cell.bbox[3] for cell in cells),
    ]
    return OcrTable(
        table_id=table_id,
        page_id=page_id,
        bbox=table_bbox,
        rows=max(cell.row for cell in cells) + 1,
        cols=max(cell.col for cell in cells) + 1,
        cells=cells,
    )


def _cells_from_bboxes(*, page_id: str, boxes: list[list[int]]) -> list[OcrCell]:
    sorted_boxes = sorted(boxes, key=lambda box: ((box[1] + box[3]) / 2, box[0]))
    heights = sorted(max(box[3] - box[1], 1) for box in sorted_boxes)
    median_height = heights[len(heights) // 2] if heights else 12
    threshold = max(median_height * 0.6, 10)
    rows: list[list[list[int]]] = []
    row_centers: list[float] = []
    for box in sorted_boxes:
        center_y = (box[1] + box[3]) / 2
        row_index = _nearest_row_index(row_centers, center_y, threshold)
        if row_index is None:
            rows.append([box])
            row_centers.append(center_y)
        else:
            rows[row_index].append(box)
            row_centers[row_index] = sum((item[1] + item[3]) / 2 for item in rows[row_index]) / len(rows[row_index])

    ordered_rows = sorted(zip(row_centers, rows), key=lambda item: item[0])
    cells: list[OcrCell] = []
    for row_index, (_center, row_boxes) in enumerate(ordered_rows):
        for col_index, box in enumerate(sorted(row_boxes, key=lambda item: item[0])):
            cells.append(
                OcrCell(
                    cell_id=f"{page_id}_r{row_index:03d}_c{col_index:03d}",
                    page_id=page_id,
                    row=row_index,
                    col=col_index,
                    bbox=box,
                    source_method="ppstructure_korean_ocr",
                )
            )
    return cells


def _nearest_row_index(row_centers: list[float], center_y: float, threshold: float) -> int | None:
    nearest_index: int | None = None
    nearest_distance = threshold
    for index, existing_center in enumerate(row_centers):
        distance = abs(existing_center - center_y)
        if distance <= nearest_distance:
            nearest_index = index
            nearest_distance = distance
    return nearest_index


def _assign_text_boxes(cells: list[OcrCell], text_boxes: list[OcrTextBox]) -> None:
    assignments: dict[str, list[OcrTextBox]] = {cell.cell_id: [] for cell in cells}
    for box in text_boxes:
        center_x = (box.bbox[0] + box.bbox[2]) / 2
        center_y = (box.bbox[1] + box.bbox[3]) / 2
        for cell in cells:
            x1, y1, x2, y2 = cell.bbox
            if x1 <= center_x <= x2 and y1 <= center_y <= y2:
                assignments[cell.cell_id].append(box)
                break

    for cell in cells:
        boxes = sorted(assignments[cell.cell_id], key=lambda item: (item.bbox[1], item.bbox[0]))
        if not boxes:
            continue
        cell.text = " ".join(box.text for box in boxes).strip()
        scores = [box.confidence for box in boxes if box.confidence is not None]
        if scores:
            cell.confidence = sum(scores) / len(scores)
        cell.raw["text_box_count"] = len(boxes)


def _extract_table_html(region: Any) -> str:
    if not isinstance(region, dict):
        return ""
    if str(region.get("type", "")).lower() not in {"table", "table_body", "table_caption"}:
        html = _html_from_any(region)
        return html if "<table" in html.lower() else ""
    return _html_from_any(region)


def _html_from_any(value: Any) -> str:
    if isinstance(value, str):
        return value if "<table" in value.lower() else ""
    if isinstance(value, dict):
        for key in ("html", "table_html"):
            html = value.get(key)
            if isinstance(html, str) and "<table" in html.lower():
                return html
        for key in ("res", "result", "table", "structure"):
            html = _html_from_any(value.get(key))
            if html:
                return html
    if isinstance(value, list):
        for item in value:
            html = _html_from_any(item)
            if html:
                return html
    return ""


def _extract_bbox(region: Any, image: Image.Image) -> list[int]:
    if isinstance(region, dict):
        for key in ("bbox", "box", "layout_bbox"):
            bbox = _bbox_from_value(region.get(key))
            if bbox:
                return bbox
        res = region.get("res")
        if isinstance(res, dict):
            bbox = _bbox_from_value(res.get("bbox") or res.get("box"))
            if bbox:
                return bbox
    return [0, 0, image.width, image.height]


def _bbox_from_value(value: Any) -> list[int]:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        if all(isinstance(item, (int, float)) for item in value[:4]):
            x1, y1, x2, y2 = [int(round(float(item))) for item in value[:4]]
            return [x1, y1, x2, y2]
        points = value[:4]
        if all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in points):
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            return [int(round(min(xs))), int(round(min(ys))), int(round(max(xs))), int(round(max(ys)))]
    return []


def _raw_region_summary(region: Any) -> dict[str, Any]:
    if not isinstance(region, dict):
        return {"backend": "ppstructure"}
    raw: dict[str, Any] = {"backend": "ppstructure"}
    for key in ("type", "bbox", "score"):
        if key in region:
            raw[key] = region[key]
    return raw
