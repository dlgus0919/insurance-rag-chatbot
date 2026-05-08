#!/usr/bin/env python3
"""Hybrid OCR vs CLOVA OCR 비교 실행 스크립트."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.parser.clova_ocr import ClovaOcrError, clova_ocr_page
from src.parser.hybrid_ocr import hybrid_ocr_page
from src.parser.ocr_engine import LayoutBlock
from src.parser.ocr_preprocessor import PreprocessResult, preprocess_page
from src.parser.pdf_extractor import extract_page_image, get_page_count

from scripts.ocr_verify import quality_metrics

EXPECTED_TABLE_KEYWORDS = {"수술종수", "수술명", "수술해설", "수술방법", "분류"}


def parse_pages_arg(value: str, total_pages: int) -> list[int]:
    pages: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError(f"잘못된 페이지 범위입니다: {part}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))

    deduped = sorted(set(pages))
    invalid = [page for page in deduped if page < 0 or page >= total_pages]
    if invalid:
        raise ValueError(f"페이지가 문서 범위를 벗어났습니다: {invalid[:5]} / total={total_pages}")
    return deduped


def score_table_header(table_json: dict) -> float:
    headers_text = " ".join(str(value) for value in table_json.get("headers", []))
    matched = sum(1 for keyword in EXPECTED_TABLE_KEYWORDS if keyword in headers_text)
    return round(matched / len(EXPECTED_TABLE_KEYWORDS), 2)


def _select_source(doc_short: str):
    candidates = [source for source in config.PDF_SOURCES if source.requires_ocr and source.doc_short == doc_short]
    if not candidates:
        raise SystemExit(f"OCR 대상 문서를 찾지 못했습니다: {doc_short}")
    return candidates[0]


def _engine_list(value: str) -> list[str]:
    if value == "all":
        return ["hybrid", "clova"]
    return [value]


def _normalize_table_json(table_json: dict | None) -> dict | None:
    if table_json is None:
        return None
    headers = [str(value) for value in table_json.get("headers", [])]
    normalized_rows: list[dict] = []
    for row in table_json.get("rows", []):
        if isinstance(row, dict):
            normalized_rows.append({str(key): str(value) for key, value in row.items()})
        else:
            values = [str(value) for value in row]
            padded = values + [""] * max(0, len(headers) - len(values))
            normalized_rows.append(dict(zip(headers, padded[: len(headers)])))
    return {"headers": headers, "rows": normalized_rows}


def _safe_average(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _build_page_result(
    *,
    engine: str,
    doc_short: str,
    page_no: int,
    blocks: list[LayoutBlock],
    prep: PreprocessResult,
    elapsed_sec: float,
    doc_dir: Path,
    status: str = "SUCCESS",
    error: str | None = None,
) -> dict:
    figure_regions = [region for region in prep.regions if region.block_type == "figure"]
    figures: list[dict] = []
    for index, region in enumerate(figure_regions):
        saved_path = prep.figure_paths[index] if index < len(prep.figure_paths) else None
        rel = str(saved_path.relative_to(doc_dir)) if saved_path is not None and saved_path.exists() else ""
        figures.append({"bbox": list(region.bbox), "saved_path": rel})

    block_entries: list[dict] = []
    block_korean_ratios: list[float] = []
    block_noise_ratios: list[float] = []
    grade_pass = grade_marginal = grade_fail = 0
    header_scores: list[float] = []
    table_blocks = text_blocks = 0

    for block in blocks:
        table_json = _normalize_table_json(block.table_json)
        quality = quality_metrics(block.text or "")
        if block.text:
            block_korean_ratios.append(float(quality.get("korean_ratio", 0.0)))
            block_noise_ratios.append(float(quality.get("noise_ratio", 1.0)))
            grade = str(quality.get("grade", "FAIL"))
            if grade == "PASS":
                grade_pass += 1
            elif grade == "MARGINAL":
                grade_marginal += 1
            else:
                grade_fail += 1

        if block.block_type == "table":
            table_blocks += 1
            if table_json is not None:
                header_scores.append(score_table_header(table_json))
        if block.block_type in {"text", "title"}:
            text_blocks += 1

        block_entries.append(
            {
                "block_type": block.block_type,
                "bbox": [int(v) for v in block.bbox],
                "text": block.text,
                "table_json": table_json,
                "source_method": block.source_method,
                "quality": quality,
            }
        )

    metrics = {
        "total_blocks": len(block_entries),
        "table_blocks": table_blocks,
        "text_blocks": text_blocks,
        "figure_blocks": len(figures),
        "avg_korean_ratio": _safe_average(block_korean_ratios),
        "avg_noise_ratio": _safe_average(block_noise_ratios),
        "grade_pass": grade_pass,
        "grade_marginal": grade_marginal,
        "grade_fail": grade_fail,
        "header_score_avg": _safe_average(header_scores),
    }

    return {
        "engine": engine,
        "doc_short": doc_short,
        "page_no": page_no,
        "elapsed_sec": round(elapsed_sec, 3),
        "status": status,
        "error": error,
        "original_image": f"p{page_no:03d}_original.png",
        "masked_image": f"p{page_no:03d}_masked.png",
        "figures": figures,
        "blocks": block_entries,
        "metrics": metrics,
    }


def _summarize_engine(results: list[dict]) -> dict:
    success = [result for result in results if result.get("status") == "SUCCESS"]
    skipped = [result for result in results if result.get("status") != "SUCCESS"]
    if not success:
        return {
            "avg_elapsed_sec": None,
            "avg_korean_ratio": None,
            "avg_noise_ratio": None,
            "table_blocks": 0,
            "header_score_avg": None,
            "grade": {"PASS": 0, "MARGINAL": 0, "FAIL": 0},
            "skipped_pages": [result["page_no"] for result in skipped],
            "status": "SKIPPED",
        }

    avg_elapsed = _safe_average([float(result["elapsed_sec"]) for result in success])
    avg_korean_ratio = _safe_average([float(result["metrics"]["avg_korean_ratio"]) for result in success])
    avg_noise_ratio = _safe_average([float(result["metrics"]["avg_noise_ratio"]) for result in success])
    table_blocks = sum(int(result["metrics"]["table_blocks"]) for result in success)
    header_score_avg = _safe_average([float(result["metrics"]["header_score_avg"]) for result in success])

    grade_pass = sum(int(result["metrics"]["grade_pass"]) for result in success)
    grade_marginal = sum(int(result["metrics"]["grade_marginal"]) for result in success)
    grade_fail = sum(int(result["metrics"]["grade_fail"]) for result in success)
    return {
        "avg_elapsed_sec": avg_elapsed,
        "avg_korean_ratio": avg_korean_ratio,
        "avg_noise_ratio": avg_noise_ratio,
        "table_blocks": table_blocks,
        "header_score_avg": header_score_avg,
        "grade": {"PASS": grade_pass, "MARGINAL": grade_marginal, "FAIL": grade_fail},
        "skipped_pages": [result["page_no"] for result in skipped],
        "status": "PARTIAL" if skipped else "SUCCESS",
    }


def _run_engine(engine: str, prep: PreprocessResult, page_name: str, timeout_sec: int) -> list[LayoutBlock]:
    if engine == "hybrid":
        return hybrid_ocr_page(prep)
    if engine == "clova":
        return clova_ocr_page(prep.masked_image, page_name=page_name, layout_regions=prep.regions, timeout_sec=timeout_sec)
    raise ValueError(f"지원하지 않는 엔진입니다: {engine}")


def run_compare(doc: str, pages_arg: str, engines: str, output_dir: Path, timeout: int = 60, save_images: bool = True) -> Path:
    source = _select_source(doc)
    if not source.path.exists():
        raise SystemExit(f"파일이 없습니다: {source.path}")

    total_pages = get_page_count(source.path)
    pages = parse_pages_arg(pages_arg, total_pages)
    selected_engines = _engine_list(engines)

    doc_dir = output_dir / source.doc_short
    doc_dir.mkdir(parents=True, exist_ok=True)

    engine_results: dict[str, list[dict]] = {engine: [] for engine in selected_engines}

    for page_no in pages:
        image = extract_page_image(source.path, page_no)
        figure_dir = doc_dir / f"p{page_no:03d}_figures"
        prep = preprocess_page(image, figure_save_dir=figure_dir, page_name=f"p{page_no:03d}")

        if save_images:
            image.save(doc_dir / f"p{page_no:03d}_original.png")
            prep.masked_image.save(doc_dir / f"p{page_no:03d}_masked.png")

        for engine in selected_engines:
            started = time.perf_counter()
            try:
                blocks = _run_engine(engine, prep, page_name=f"p{page_no:03d}", timeout_sec=timeout)
                elapsed = time.perf_counter() - started
                page_result = _build_page_result(
                    engine=engine,
                    doc_short=source.doc_short,
                    page_no=page_no,
                    blocks=blocks,
                    prep=prep,
                    elapsed_sec=elapsed,
                    doc_dir=doc_dir,
                )
                print(
                    f"[ocr_compare] {engine} p{page_no:03d}: "
                    f"blocks={len(blocks)}, tables={page_result['metrics']['table_blocks']}, "
                    f"header={page_result['metrics']['header_score_avg']}, elapsed={page_result['elapsed_sec']}s"
                )
            except ClovaOcrError as exc:
                elapsed = time.perf_counter() - started
                page_result = _build_page_result(
                    engine=engine,
                    doc_short=source.doc_short,
                    page_no=page_no,
                    blocks=[],
                    prep=prep,
                    elapsed_sec=elapsed,
                    doc_dir=doc_dir,
                    status="SKIPPED",
                    error=str(exc),
                )
                print(f"[ocr_compare] {engine} p{page_no:03d} skipped: {exc}")

            json_path = doc_dir / f"p{page_no:03d}_{engine}.json"
            json_path.write_text(json.dumps(page_result, ensure_ascii=False, indent=2), encoding="utf-8")
            engine_results[engine].append(page_result)

    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "doc_short": source.doc_short,
        "pages": pages,
        "engines": {engine: _summarize_engine(results) for engine, results in engine_results.items()},
    }
    summary_path = doc_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ocr_compare] summary: {summary_path}")
    return summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Hybrid OCR vs CLOVA OCR 비교")
    parser.add_argument("--doc", default="실무가이드")
    parser.add_argument("--pages", default="60-70")
    parser.add_argument("--engines", choices=["hybrid", "clova", "all"], default="all")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "ocr_compare")
    parser.add_argument("--timeout", type=int, default=60, help="CLOVA API timeout (sec)")
    parser.add_argument("--save-images", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    run_compare(
        doc=args.doc,
        pages_arg=args.pages,
        engines=args.engines,
        output_dir=args.output_dir,
        timeout=args.timeout,
        save_images=args.save_images,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

