from __future__ import annotations

from PIL import Image

import src.parser.hybrid_ocr as hybrid_ocr
from src.parser.ocr_engine import LayoutBlock
from src.parser.ocr_preprocessor import LayoutRegion, PreprocessResult


class _DummyKoreanOCR:
    def ocr(self, _arr, cls: bool = False):  # noqa: ANN001
        return [[([0, 0, 10, 10], ("수술종수", 0.99))]]


def test_hybrid_text_block(monkeypatch) -> None:
    prep = PreprocessResult(
        original_image=Image.new("RGB", (100, 100), color="white"),
        masked_image=Image.new("RGB", (100, 100), color="white"),
        regions=[LayoutRegion(block_type="text", bbox=(0, 0, 80, 20))],
        figure_paths=[],
    )

    monkeypatch.setattr(hybrid_ocr, "_get_korean_ocr", lambda: _DummyKoreanOCR())

    blocks = hybrid_ocr.hybrid_ocr_page(prep)

    assert len(blocks) == 1
    assert blocks[0].block_type == "text"
    assert blocks[0].source_method == "ocr_ppstructure_twopass"
    assert "수술종수" in blocks[0].text


def test_hybrid_figure_skip(monkeypatch) -> None:
    prep = PreprocessResult(
        original_image=Image.new("RGB", (120, 120), color="white"),
        masked_image=Image.new("RGB", (120, 120), color="white"),
        regions=[
            LayoutRegion(block_type="figure", bbox=(0, 0, 50, 50)),
            LayoutRegion(block_type="text", bbox=(60, 0, 110, 30)),
        ],
        figure_paths=[],
    )
    monkeypatch.setattr(hybrid_ocr, "_get_korean_ocr", lambda: _DummyKoreanOCR())

    blocks = hybrid_ocr.hybrid_ocr_page(prep)

    assert all(block.block_type != "figure" for block in blocks)
    assert len(blocks) == 1


def test_hybrid_fallback(monkeypatch) -> None:
    prep = PreprocessResult(
        original_image=Image.new("RGB", (100, 100), color="white"),
        masked_image=Image.new("RGB", (100, 100), color="white"),
        regions=[],
        figure_paths=[],
    )
    sentinel = [LayoutBlock(block_type="text", bbox=[0, 0, 10, 10], text="fallback", source_method="ocr_easyocr")]
    monkeypatch.setattr(hybrid_ocr, "_get_korean_ocr", lambda: _DummyKoreanOCR())
    monkeypatch.setattr(hybrid_ocr, "run_easyocr_fallback", lambda _image: sentinel)

    blocks = hybrid_ocr.hybrid_ocr_page(prep)

    assert blocks == sentinel

