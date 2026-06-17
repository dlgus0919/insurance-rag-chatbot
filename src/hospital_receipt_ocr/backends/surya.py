"""C-plan backend boundary for Surya-based table extraction."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from PIL import Image

from ..models import OcrTable
from .table_html import html_table_to_ocr_table


@dataclass
class SuryaAdapter:
    """Opt-in Surya wrapper.

    Surya is treated as an experimental local backend because some execution
    modes may start model-serving components. The default path never starts
    inference; it records a degraded run instead.
    """

    allow_inference: bool = False
    unavailable_reason: str = ""

    def extract_tables(self, image: Image.Image, *, page_id: str) -> list[OcrTable]:
        if not self.allow_inference:
            self.unavailable_reason = "Surya inference is disabled. Pass --allow-experimental-surya-inference to opt in."
            return []
        if importlib.util.find_spec("surya") is None:
            self.unavailable_reason = "surya package is not installed in this runtime."
            return []

        try:
            return self._extract_with_optional_interfaces(image, page_id=page_id)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # pragma: no cover - Surya API/version dependent
            self.unavailable_reason = f"Surya 실행 실패: {exc.__class__.__name__}: {exc}"
            return []

    def _extract_with_optional_interfaces(self, image: Image.Image, *, page_id: str) -> list[OcrTable]:
        """Run Surya v2 table-recognition full HTML path."""

        predictions = self._try_surya_predictions(image)
        tables: list[OcrTable] = []
        for index, prediction in enumerate(predictions, start=1):
            html = prediction.get("html", "")
            if not html:
                continue
            table = html_table_to_ocr_table(
                page_id=page_id,
                table_id=f"{page_id}_surya_t{index:03d}",
                bbox=prediction.get("bbox") or [0, 0, image.width, image.height],
                html=html,
                source_method="surya",
                raw={
                    "backend": "surya",
                    "prediction_type": prediction.get("prediction_type", ""),
                    "source": prediction.get("source", ""),
                },
            )
            if table is not None:
                tables.append(table)
        if not tables and not self.unavailable_reason:
            self.unavailable_reason = "Surya ran but did not return supported table HTML output."
        return tables

    def _try_surya_predictions(self, image: Image.Image) -> list[dict[str, Any]]:
        """Run current Surya v2 table/OCR APIs and collect table HTML outputs."""

        from surya.inference import SuryaInferenceManager  # type: ignore
        from surya.table_rec import TableRecPredictor  # type: ignore

        table_predictor = TableRecPredictor(SuryaInferenceManager())
        full_results = table_predictor.predict_full([image])
        return _collect_table_items(full_results, image=image)


def extract_tables_from_image(
    image: Image.Image,
    *,
    page_id: str,
    surya: SuryaAdapter | None = None,
    allow_inference: bool = False,
) -> list[OcrTable]:
    adapter = surya or SuryaAdapter(allow_inference=allow_inference)
    return adapter.extract_tables(image, page_id=page_id)


def _collect_table_items(results: Any, *, image: Image.Image) -> list[dict[str, Any]]:
    """Collect table HTML from Surya v2 TableResult objects."""

    items: list[dict[str, Any]] = []
    for result in results or []:
        html = getattr(result, "html", "")
        if isinstance(html, str) and "<table" in html.lower():
            items.append(_table_item(result, html=html, image=image))
    return items


def _table_item(value: Any, *, html: str, image: Image.Image) -> dict[str, Any]:
    return {
        "html": html,
        "bbox": _extract_prediction_bbox(value, image),
        "prediction_type": type(value).__name__,
        "source": "table_rec_full",
    }


def _extract_prediction_bbox(prediction: Any, image: Image.Image) -> list[int]:
    for key in ("image_bbox", "bbox"):
        value = getattr(prediction, key, None)
        bbox = _bbox_from_value(value)
        if bbox:
            return bbox
    value = getattr(prediction, "polygon", None)
    bbox = _bbox_from_value(value)
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
