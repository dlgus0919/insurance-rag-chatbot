"""D-plan backend: TATR table structure plus PaddleOCR text assignment."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from PIL import Image

from ..models import OcrCell, OcrTable
from .opencv_paddle import PaddleOcrAdapter
from .ppstructure import _assign_text_boxes


@dataclass
class TatrOcrAdapter:
    detection_model: str = "microsoft/table-transformer-detection"
    structure_model: str = "microsoft/table-transformer-structure-recognition"
    threshold: float = 0.7
    unavailable_reason: str = ""
    last_page_text: str = ""
    _det_bundle: tuple[Any, Any] | None = None
    _struct_bundle: tuple[Any, Any] | None = None
    _device: str = ""

    def extract_tables(self, image: Image.Image, *, page_id: str, text_ocr: PaddleOcrAdapter | None = None) -> list[OcrTable]:
        if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("torch") is None:
            self.unavailable_reason = "transformers/torch package is not installed in this runtime."
            return []
        try:
            table_boxes = self._table_boxes(image) or [[0, 0, image.width, image.height]]
            text_boxes = (text_ocr or PaddleOcrAdapter()).ocr_image(image)
            self.last_page_text = "\n".join(box.text for box in text_boxes if box.text)
            tables: list[OcrTable] = []
            for index, table_box in enumerate(table_boxes, start=1):
                cells = self._cells_for_table(image, page_id=page_id, table_box=table_box)
                if not cells:
                    continue
                _assign_text_boxes(cells, text_boxes)
                tables.append(
                    OcrTable(
                        table_id=f"{page_id}_tatr_t{index:03d}",
                        page_id=page_id,
                        bbox=table_box,
                        rows=max(cell.row for cell in cells) + 1,
                        cols=max(cell.col for cell in cells) + 1,
                        cells=cells,
                    )
                )
            if not tables:
                self.unavailable_reason = "TATR ran but did not return usable row/column intersections."
            return tables
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # pragma: no cover - model/runtime dependent
            self.unavailable_reason = f"TATR 실행 실패: {exc.__class__.__name__}: {exc}"
            return []

    def _table_boxes(self, image: Image.Image) -> list[list[int]]:
        detections = self._predict(image, self.detection_model)
        boxes = [item["bbox"] for item in detections if "table" in item["label"]]
        return _dedupe_boxes(boxes)

    def _cells_for_table(self, image: Image.Image, *, page_id: str, table_box: list[int]) -> list[OcrCell]:
        crop = image.crop(tuple(table_box))
        detections = self._predict(crop, self.structure_model)
        rows = sorted((item["bbox"] for item in detections if item["label"] == "table row"), key=lambda box: box[1])
        cols = sorted((item["bbox"] for item in detections if item["label"] == "table column"), key=lambda box: box[0])
        cells: list[OcrCell] = []
        for row_index, row in enumerate(rows):
            for col_index, col in enumerate(cols):
                bbox = [
                    table_box[0] + max(row[0], col[0]),
                    table_box[1] + max(row[1], col[1]),
                    table_box[0] + min(row[2], col[2]),
                    table_box[1] + min(row[3], col[3]),
                ]
                if bbox[2] - bbox[0] < 8 or bbox[3] - bbox[1] < 8:
                    continue
                cells.append(
                    OcrCell(
                        cell_id=f"{page_id}_r{row_index:03d}_c{col_index:03d}",
                        page_id=page_id,
                        row=row_index,
                        col=col_index,
                        bbox=bbox,
                        source_method="tatr_ocr",
                        raw={"backend": "tatr_ocr"},
                    )
                )
        return cells

    def _predict(self, image: Image.Image, model_name: str) -> list[dict[str, Any]]:
        import torch
        from transformers import AutoImageProcessor, TableTransformerForObjectDetection

        processor, model = self._load_bundle(model_name, AutoImageProcessor, TableTransformerForObjectDetection, torch)
        inputs = {key: value.to(self._device_name(torch)) for key, value in processor(images=image, return_tensors="pt").items()}
        with torch.no_grad():
            outputs = model(**inputs)
        target_sizes = torch.tensor([image.size[::-1]])
        results = processor.post_process_object_detection(outputs, threshold=self.threshold, target_sizes=target_sizes)[0]
        id2label = model.config.id2label
        return [
            {"label": str(id2label[int(label)]).lower(), "score": float(score), "bbox": _clean_bbox(box.tolist(), image)}
            for score, label, box in zip(results["scores"], results["labels"], results["boxes"])
        ]

    def _load_bundle(self, model_name: str, processor_cls: Any, model_cls: Any, torch_module: Any) -> tuple[Any, Any]:
        if model_name == self.detection_model and self._det_bundle is not None:
            return self._det_bundle
        if model_name == self.structure_model and self._struct_bundle is not None:
            return self._struct_bundle
        device = self._device_name(torch_module)
        bundle = (processor_cls.from_pretrained(model_name), model_cls.from_pretrained(model_name).to(device))
        if model_name == self.detection_model:
            self._det_bundle = bundle
        elif model_name == self.structure_model:
            self._struct_bundle = bundle
        return bundle

    def _device_name(self, torch_module: Any) -> str:
        if not self._device:
            self._device = "cuda" if torch_module.cuda.is_available() else "cpu"
        return self._device


def extract_tables_from_image(
    image: Image.Image,
    *,
    page_id: str,
    tatr: TatrOcrAdapter | None = None,
    text_ocr: PaddleOcrAdapter | None = None,
) -> list[OcrTable]:
    adapter = tatr or TatrOcrAdapter()
    return adapter.extract_tables(image, page_id=page_id, text_ocr=text_ocr)


def _clean_bbox(box: list[float], image: Image.Image) -> list[int]:
    x1, y1, x2, y2 = [int(round(value)) for value in box[:4]]
    return [max(0, x1), max(0, y1), min(image.width, x2), min(image.height, y2)]


def _dedupe_boxes(boxes: list[list[int]]) -> list[list[int]]:
    deduped: list[list[int]] = []
    for box in sorted(boxes, key=lambda item: (item[1], item[0])):
        if any(_iou(box, existing) > 0.8 for existing in deduped):
            continue
        deduped.append(box)
    return deduped


def _iou(a: list[int], b: list[int]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return inter / max(area_a + area_b - inter, 1)
