from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PIL import Image
import pytest

import scripts.run_true_hybrid_local as runner
from scripts.run_clova_local import _update_summary
from src.parser.clova_ocr import ClovaOcrError
from src.parser.ocr_engine import LayoutBlock
from src.parser.ocr_preprocessor import LayoutRegion, PreprocessResult


@dataclass
class _CallRecorder:
    layout_regions: list | None = None


def _prepare_doc(tmp_path: Path, page_no: int = 60) -> Path:
    doc_dir = tmp_path / "실무가이드"
    doc_dir.mkdir(parents=True)
    Image.new("RGB", (120, 120), color="white").save(doc_dir / f"p{page_no:03d}_original.png")
    (doc_dir / "summary.json").write_text(
        json.dumps(
            {
                "doc_short": "실무가이드",
                "engines": {
                    "hybrid": {"status": "SUCCESS"},
                    "clova": {"status": "SUCCESS"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return doc_dir


def test_run_true_hybrid_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc_dir = _prepare_doc(tmp_path)
    recorder = _CallRecorder()

    def fake_preprocess_page(image, figure_save_dir: Path, page_name: str) -> PreprocessResult:
        figure_save_dir.mkdir(parents=True)
        figure_path = figure_save_dir / f"{page_name}_fig00.png"
        image.crop((80, 80, 100, 100)).save(figure_path)
        return PreprocessResult(
            original_image=image,
            masked_image=image.copy(),
            regions=[
                LayoutRegion("table", (0, 0, 80, 40)),
                LayoutRegion("figure", (80, 80, 100, 100)),
            ],
            figure_paths=[figure_path],
        )

    def fake_clova_ocr_page(image, page_name: str, layout_regions: list, timeout_sec: int) -> list[LayoutBlock]:
        recorder.layout_regions = layout_regions
        return [
            LayoutBlock(
                block_type="table",
                bbox=[0, 0, 80, 40],
                text="수술종수 | 수술명\n1종 | 예시",
                table_json={"headers": ["수술종수", "수술명"], "rows": [{"수술종수": "1종", "수술명": "예시"}]},
                source_method="ocr_clova",
            )
        ]

    monkeypatch.setattr(runner, "preprocess_page", fake_preprocess_page)
    monkeypatch.setattr(runner, "clova_ocr_page", fake_clova_ocr_page)

    runner.run_true_hybrid_local("실무가이드", "60", tmp_path, 60)

    output = json.loads((doc_dir / "p060_true_hybrid.json").read_text(encoding="utf-8"))
    assert output["engine"] == "true_hybrid"
    assert output["status"] == "SUCCESS"
    assert output["blocks"][0]["block_type"] == "table"
    assert output["blocks"][0]["quality"]["grade"] == "PASS"
    assert output["figures"][0]["saved_path"] == "p060_true_hybrid_figures/p060_fig00.png"
    assert recorder.layout_regions is not None


def test_run_true_hybrid_clova_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc_dir = _prepare_doc(tmp_path)

    def fake_preprocess_page(image, figure_save_dir: Path, page_name: str) -> PreprocessResult:
        return PreprocessResult(
            original_image=image,
            masked_image=image.copy(),
            regions=[LayoutRegion("text", (0, 0, 80, 40))],
            figure_paths=[],
        )

    def fake_clova_ocr_page(image, page_name: str, layout_regions: list, timeout_sec: int) -> list[LayoutBlock]:
        raise ClovaOcrError("API 요청 실패")

    monkeypatch.setattr(runner, "preprocess_page", fake_preprocess_page)
    monkeypatch.setattr(runner, "clova_ocr_page", fake_clova_ocr_page)

    runner.run_true_hybrid_local("실무가이드", "60", tmp_path, 60)

    output = json.loads((doc_dir / "p060_true_hybrid.json").read_text(encoding="utf-8"))
    assert output["status"] == "SKIPPED"
    assert output["error"] == "API 요청 실패"
    assert output["blocks"] == []


def test_run_true_hybrid_missing_png(tmp_path: Path) -> None:
    doc_dir = tmp_path / "실무가이드"
    doc_dir.mkdir(parents=True)

    runner.run_true_hybrid_local("실무가이드", "60", tmp_path, 60)

    output = json.loads((doc_dir / "p060_true_hybrid.json").read_text(encoding="utf-8"))
    assert output["status"] == "SKIPPED"
    assert "원본 이미지 없음" in output["error"]


def test_update_summary_true_hybrid_key(tmp_path: Path) -> None:
    doc_dir = tmp_path / "실무가이드"
    doc_dir.mkdir(parents=True)
    (doc_dir / "summary.json").write_text(
        json.dumps(
            {
                "doc_short": "실무가이드",
                "engines": {
                    "hybrid": {"status": "SUCCESS"},
                    "clova": {"status": "SUCCESS"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _update_summary(
        tmp_path,
        "실무가이드",
        [
            {
                "page_no": 60,
                "elapsed_sec": 5.0,
                "status": "SUCCESS",
                "blocks": [{"block_type": "text", "quality": {"korean_ratio": 0.8, "noise_ratio": 0.0, "grade": "PASS"}}],
                "metrics": {"header_score_avg": 0.0},
            }
        ],
        engine_key="true_hybrid",
    )

    summary = json.loads((doc_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["engines"]["hybrid"] == {"status": "SUCCESS"}
    assert summary["engines"]["clova"] == {"status": "SUCCESS"}
    assert summary["engines"]["true_hybrid"]["status"] == "SUCCESS"
    assert "true_hybrid_run_at" in summary
