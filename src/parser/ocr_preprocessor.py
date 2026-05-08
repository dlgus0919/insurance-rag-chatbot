"""OCR 공통 전처리: PP-Structure 레이아웃 탐지 + figure 마스킹."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from src.parser.ocr_engine import _get_structure_engine

FIGURE_SHRINK_PX = 8


@dataclass
class LayoutRegion:
    """레이아웃 탐지 단위 블록."""

    block_type: str
    bbox: tuple[int, int, int, int]


@dataclass
class PreprocessResult:
    """페이지 전처리 결과."""

    original_image: Image.Image
    masked_image: Image.Image
    regions: list[LayoutRegion]
    figure_paths: list[Path]


def _normalize_block_type(block_type: str) -> str:
    lowered = (block_type or "text").lower()
    if lowered == "table":
        return "table"
    if lowered in {"figure", "image"}:
        return "figure"
    if lowered == "title":
        return "title"
    return "text"


def _normalize_bbox(bbox_raw: object, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) < 4:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(v))) for v in bbox_raw[:4]]
    except (TypeError, ValueError):
        return None
    x1 = max(0, min(width, x1))
    x2 = max(0, min(width, x2))
    y1 = max(0, min(height, y1))
    y2 = max(0, min(height, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _white_fill_for_mode(mode: str):
    if mode == "L":
        return 255
    if mode == "RGBA":
        return (255, 255, 255, 255)
    return (255, 255, 255)


def preprocess_page(
    image: Image.Image,
    figure_save_dir: Path | None = None,
    page_name: str = "page",
) -> PreprocessResult:
    """PP-Structure로 레이아웃을 탐지하고 figure 영역을 마스킹한다."""

    img_array = np.array(image)
    structure_results = _get_structure_engine()(img_array)
    width, height = image.size

    regions: list[LayoutRegion] = []
    figure_bboxes: list[tuple[int, int, int, int]] = []
    figure_paths: list[Path] = []

    for result in structure_results:
        bbox = _normalize_bbox(result.get("bbox"), width=width, height=height)
        if bbox is None:
            continue
        block_type = _normalize_block_type(str(result.get("type", "text")))
        regions.append(LayoutRegion(block_type=block_type, bbox=bbox))

        if block_type != "figure":
            continue
        figure_bboxes.append(bbox)

        if figure_save_dir is not None:
            figure_save_dir.mkdir(parents=True, exist_ok=True)
            fig_idx = len(figure_paths)
            fig_path = figure_save_dir / f"{page_name}_fig{fig_idx:02d}.png"
            image.crop(bbox).save(fig_path)
            figure_paths.append(fig_path)

    masked = image.copy()
    draw = ImageDraw.Draw(masked)
    fill = _white_fill_for_mode(masked.mode)
    for x1, y1, x2, y2 in figure_bboxes:
        sx1 = x1 + FIGURE_SHRINK_PX
        sy1 = y1 + FIGURE_SHRINK_PX
        sx2 = x2 - FIGURE_SHRINK_PX
        sy2 = y2 - FIGURE_SHRINK_PX
        if sx2 <= sx1 or sy2 <= sy1:
            continue
        draw.rectangle([sx1, sy1, sx2, sy2], fill=fill)

    return PreprocessResult(
        original_image=image,
        masked_image=masked,
        regions=regions,
        figure_paths=figure_paths,
    )

