from __future__ import annotations

from pathlib import Path

from PIL import Image

import src.parser.ocr_preprocessor as ocr_preprocessor
from src.parser.ocr_preprocessor import FIGURE_SHRINK_PX, preprocess_page


def _mock_structure(results: list[dict]):
    return lambda _arr: results


def test_preprocess_no_figures(monkeypatch) -> None:
    monkeypatch.setattr(ocr_preprocessor, "_get_structure_engine", lambda: _mock_structure([{"type": "text", "bbox": [10, 10, 60, 40]}]))
    image = Image.new("RGB", (100, 100), color="black")

    prep = preprocess_page(image)

    assert prep.figure_paths == []
    assert prep.regions[0].block_type == "text"
    assert list(prep.masked_image.getdata()) == list(image.getdata())


def test_preprocess_figure_masking(monkeypatch) -> None:
    monkeypatch.setattr(ocr_preprocessor, "_get_structure_engine", lambda: _mock_structure([{"type": "figure", "bbox": [10, 10, 50, 50]}]))
    image = Image.new("RGB", (100, 100), color="black")

    prep = preprocess_page(image)

    assert prep.regions[0].block_type == "figure"
    center = prep.masked_image.getpixel((30, 30))
    edge = prep.masked_image.getpixel((12, 12))
    assert center == (255, 255, 255)
    assert edge == (0, 0, 0)


def test_preprocess_figure_saved(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ocr_preprocessor, "_get_structure_engine", lambda: _mock_structure([{"type": "figure", "bbox": [10, 10, 50, 50]}]))
    image = Image.new("RGB", (100, 100), color="black")

    prep = preprocess_page(image, figure_save_dir=tmp_path / "figs", page_name="p066")

    assert len(prep.figure_paths) == 1
    assert prep.figure_paths[0].exists()
    assert prep.figure_paths[0].name == "p066_fig00.png"


def test_preprocess_shrink(monkeypatch) -> None:
    monkeypatch.setattr(ocr_preprocessor, "_get_structure_engine", lambda: _mock_structure([{"type": "figure", "bbox": [10, 10, 40, 40]}]))
    image = Image.new("RGB", (80, 80), color="black")

    prep = preprocess_page(image)

    inner_x = 10 + FIGURE_SHRINK_PX + 1
    inner_y = 10 + FIGURE_SHRINK_PX + 1
    outer_x = 10 + FIGURE_SHRINK_PX - 1
    outer_y = 10 + FIGURE_SHRINK_PX - 1
    assert prep.masked_image.getpixel((inner_x, inner_y)) == (255, 255, 255)
    assert prep.masked_image.getpixel((outer_x, outer_y)) == (0, 0, 0)
