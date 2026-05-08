#!/usr/bin/env python3
"""로컬 환경에서 PP-Structure 레이아웃과 CLOVA OCR을 결합해 실행한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_clova_local import _build_metrics, _serialize_blocks, _update_summary, parse_pages
from src.parser.clova_ocr import ClovaOcrError, clova_ocr_page
from src.parser.ocr_preprocessor import preprocess_page


def _relative_to_doc(path: Path, doc_dir: Path) -> str:
    try:
        return str(path.relative_to(doc_dir))
    except ValueError:
        return str(path)


def _extract_figures(prep, doc_dir: Path) -> list[dict]:
    figure_regions = [region for region in prep.regions if region.block_type == "figure"]
    figures: list[dict] = []
    for region, figure_path in zip(figure_regions, prep.figure_paths):
        figures.append(
            {
                "bbox": [int(value) for value in region.bbox],
                "saved_path": _relative_to_doc(Path(figure_path), doc_dir),
            }
        )
    return figures


def _write_page_json(
    doc_short: str,
    doc_dir: Path,
    page_no: int,
    elapsed_sec: float,
    *,
    status: str,
    error: str | None,
    blocks: list[dict],
    figures: list[dict],
) -> dict:
    metrics = _build_metrics(blocks, figure_blocks=len(figures) if status == "SUCCESS" else 0)
    payload = {
        "engine": "true_hybrid",
        "doc_short": doc_short,
        "page_no": page_no,
        "elapsed_sec": round(elapsed_sec, 3),
        "status": status,
        "error": error,
        "original_image": f"p{page_no:03d}_original.png",
        "masked_image": None,
        "figures": figures,
        "blocks": blocks,
        "metrics": metrics,
    }
    output_path = doc_dir / f"p{page_no:03d}_true_hybrid.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_true_hybrid_local(doc_short: str, pages_arg: str, output_dir: Path, timeout_sec: int) -> None:
    doc_dir = output_dir / doc_short
    if not doc_dir.exists():
        raise FileNotFoundError(f"결과 디렉터리를 찾을 수 없습니다: {doc_dir}")

    pages = parse_pages(pages_arg)
    if not pages:
        raise ValueError("처리할 페이지가 없습니다.")

    results: list[dict] = []
    success = skipped = 0
    total_started = time.perf_counter()

    for page_no in pages:
        page_name = f"p{page_no:03d}"
        original_path = doc_dir / f"{page_name}_original.png"
        if not original_path.exists():
            result = _write_page_json(
                doc_short,
                doc_dir,
                page_no,
                0.0,
                status="SKIPPED",
                error=f"원본 이미지 없음: {original_path.name}",
                blocks=[],
                figures=[],
            )
            results.append(result)
            skipped += 1
            print(f"[run_true_hybrid_local] {page_name} -> SKIPPED (원본 이미지 없음)")
            continue

        started = time.perf_counter()
        figure_save_dir = doc_dir / f"{page_name}_true_hybrid_figures"
        try:
            with Image.open(original_path) as image:
                image.load()
                prep = preprocess_page(image, figure_save_dir=figure_save_dir, page_name=page_name)
                layout_regions_no_fig = [region for region in prep.regions if region.block_type != "figure"]
                blocks = clova_ocr_page(
                    image,
                    page_name=page_name,
                    layout_regions=layout_regions_no_fig,
                    timeout_sec=timeout_sec,
                )
            elapsed = time.perf_counter() - started
            figures = _extract_figures(prep, doc_dir)
            block_payload = _serialize_blocks(blocks)
            result = _write_page_json(
                doc_short,
                doc_dir,
                page_no,
                elapsed,
                status="SUCCESS",
                error=None,
                blocks=block_payload,
                figures=figures,
            )
            results.append(result)
            success += 1
            print(f"[run_true_hybrid_local] {page_name} -> SUCCESS ({len(block_payload)}블록, {elapsed:.1f}초)")
        except ClovaOcrError as exc:
            elapsed = time.perf_counter() - started
            result = _write_page_json(
                doc_short,
                doc_dir,
                page_no,
                elapsed,
                status="SKIPPED",
                error=str(exc),
                blocks=[],
                figures=[],
            )
            results.append(result)
            skipped += 1
            print(f"[run_true_hybrid_local] {page_name} -> SKIPPED ({exc})")

    _update_summary(output_dir, doc_short, results, engine_key="true_hybrid")
    total_elapsed = time.perf_counter() - total_started
    print("=== 완료 ===")
    print(f"SUCCESS: {success}/{len(pages)} | SKIPPED: {skipped}/{len(pages)} | 총 소요: {total_elapsed:.1f}초")
    print(f"저장 위치: {doc_dir}")


def main() -> int:
    load_dotenv(Path(__file__).parent.parent / ".env")

    parser = argparse.ArgumentParser(description="로컬 True Hybrid OCR 결과 생성")
    parser.add_argument("--doc", default="실무가이드")
    parser.add_argument("--pages", default="60-70")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "ocr_compare")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    run_true_hybrid_local(args.doc, args.pages, args.output_dir, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
