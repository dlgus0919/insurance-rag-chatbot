#!/usr/bin/env python3
"""Two-Pass OCR vs CLOVA OCR 비교 스크립트."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
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
from src.parser.ocr_engine import LayoutBlock, ocr_page
from src.parser.pdf_extractor import extract_page_image, get_page_count

from scripts.ocr_verify import quality_metrics

EXPECTED_TABLE_KEYWORDS = {"수술종수", "수술명", "수술해설", "수술방법", "분류"}


@dataclass
class PageRunResult:
    page_no: int
    elapsed_sec: float
    metrics: dict
    table_blocks: int
    table_cells: int
    header_score_avg: float


def parse_pages_arg(value: str, total_pages: int) -> list[int]:
    """0-indexed 페이지 범위 파서."""

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
    """헤더 키워드 포함 점수(0~1)."""

    headers_text = " ".join(str(value) for value in table_json.get("headers", []))
    matched = sum(1 for keyword in EXPECTED_TABLE_KEYWORDS if keyword in headers_text)
    return round(matched / len(EXPECTED_TABLE_KEYWORDS), 2)


def _count_table_cells(table_json: dict) -> int:
    headers = table_json.get("headers", [])
    rows = table_json.get("rows", [])
    if not headers:
        return 0
    return len(headers) * (len(rows) + 1)


def _blocks_to_text(blocks: list[LayoutBlock]) -> str:
    texts = [block.text for block in blocks if block.text]
    return "\n\n".join(texts)


def _tables_text(blocks: list[LayoutBlock]) -> str:
    parts: list[str] = []
    for index, block in enumerate(blocks):
        if block.block_type != "table":
            continue
        label = f"[table_{index:02d}]"
        parts.append(label)
        parts.append(block.text or "")
    return "\n".join(parts)


def _serialize_blocks(blocks: list[LayoutBlock]) -> list[dict]:
    return [asdict(block) for block in blocks]


def _select_source(doc_short: str):
    candidates = [source for source in config.PDF_SOURCES if source.requires_ocr and source.doc_short == doc_short]
    if not candidates:
        raise SystemExit(f"OCR 대상 문서를 찾지 못했습니다: {doc_short}")
    return candidates[0]


def _engine_list(value: str) -> list[str]:
    if value == "all":
        return ["twopass", "clova"]
    return [value]


def _ocr_by_engine(engine: str, image, page_name: str) -> list[LayoutBlock]:
    if engine == "twopass":
        return ocr_page(image)
    if engine == "clova":
        return clova_ocr_page(image, page_name=page_name)
    raise ValueError(f"unknown engine: {engine}")


def _write_page_files(
    out_dir: Path,
    engine: str,
    page_no: int,
    blocks: list[LayoutBlock],
) -> PageRunResult:
    blocks_json_path = out_dir / f"{engine}_p{page_no:03d}_blocks.json"
    text_path = out_dir / f"{engine}_p{page_no:03d}_text.txt"
    table_text_path = out_dir / f"{engine}_p{page_no:03d}_tables.txt"

    blocks_json_path.write_text(json.dumps(_serialize_blocks(blocks), ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text(_blocks_to_text(blocks), encoding="utf-8")
    table_text_path.write_text(_tables_text(blocks), encoding="utf-8")

    table_scores: list[float] = []
    table_cells = 0
    table_count = 0
    for block in blocks:
        if block.block_type != "table":
            continue
        table_count += 1
        table_json = block.table_json or {"headers": [], "rows": []}
        table_scores.append(score_table_header(table_json))
        table_cells += _count_table_cells(table_json)

    metrics = quality_metrics(_blocks_to_text(blocks))
    return PageRunResult(
        page_no=page_no,
        elapsed_sec=0.0,
        metrics=metrics,
        table_blocks=table_count,
        table_cells=table_cells,
        header_score_avg=round(sum(table_scores) / len(table_scores), 3) if table_scores else 0.0,
    )


def _summarize_results(results: dict[str, list[PageRunResult]], skipped: dict[str, str]) -> str:
    lines = [
        "=== OCR Compare Summary ===",
        f"run_at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    for engine, page_results in results.items():
        if skipped.get(engine):
            lines.append(f"[{engine}] SKIPPED: {skipped[engine]}")
            lines.append("")
            continue
        if not page_results:
            lines.append(f"[{engine}] no results")
            lines.append("")
            continue

        avg_elapsed = round(sum(result.elapsed_sec for result in page_results) / len(page_results), 3)
        avg_korean_ratio = round(sum(result.metrics["korean_ratio"] for result in page_results) / len(page_results), 3)
        avg_noise_ratio = round(sum(result.metrics["noise_ratio"] for result in page_results) / len(page_results), 3)
        total_tables = sum(result.table_blocks for result in page_results)
        total_cells = sum(result.table_cells for result in page_results)
        header_score = round(sum(result.header_score_avg for result in page_results) / len(page_results), 3)
        pass_count = sum(1 for result in page_results if result.metrics["grade"] == "PASS")
        marginal_count = sum(1 for result in page_results if result.metrics["grade"] == "MARGINAL")
        fail_count = sum(1 for result in page_results if result.metrics["grade"] == "FAIL")

        lines.extend(
            [
                f"[{engine}]",
                f"pages: {len(page_results)}",
                f"avg_elapsed_sec: {avg_elapsed}",
                f"avg_korean_ratio: {avg_korean_ratio}",
                f"avg_noise_ratio: {avg_noise_ratio}",
                f"table_blocks: {total_tables}",
                f"table_cells: {total_cells}",
                f"header_score_avg: {header_score}",
                f"grade: PASS={pass_count}, MARGINAL={marginal_count}, FAIL={fail_count}",
                "",
            ]
        )

    return "\n".join(lines) + "\n"


def run_compare(doc: str, pages_arg: str, engines: str, output_dir: Path) -> Path:
    source = _select_source(doc)
    if not source.path.exists():
        raise SystemExit(f"파일이 없습니다: {source.path}")

    total_pages = get_page_count(source.path)
    pages = parse_pages_arg(pages_arg, total_pages)
    engine_list = _engine_list(engines)

    out_dir = output_dir / source.doc_short
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.txt"

    all_results: dict[str, list[PageRunResult]] = {engine: [] for engine in engine_list}
    skipped: dict[str, str] = {}

    for page_no in pages:
        image = extract_page_image(source.path, page_no)
        for engine in engine_list:
            if skipped.get(engine):
                continue
            page_name = f"{source.doc_short}_p{page_no:03d}"
            started = time.perf_counter()
            try:
                blocks = _ocr_by_engine(engine, image, page_name=page_name)
            except ClovaOcrError as exc:
                skipped[engine] = str(exc)
                print(f"[ocr_compare] {engine} skipped: {exc}")
                continue
            elapsed = time.perf_counter() - started

            page_result = _write_page_files(out_dir, engine, page_no, blocks)
            page_result.elapsed_sec = round(elapsed, 3)
            all_results[engine].append(page_result)
            print(
                f"[ocr_compare] {engine} p{page_no:03d}: "
                f"blocks={len(blocks)}, tables={page_result.table_blocks}, "
                f"header_score={page_result.header_score_avg}, elapsed={page_result.elapsed_sec}s"
            )

    summary = _summarize_results(all_results, skipped)
    summary_path.write_text(summary, encoding="utf-8")
    print(f"[ocr_compare] summary: {summary_path}")
    return summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Two-Pass OCR vs CLOVA OCR 비교")
    parser.add_argument("--doc", default="실무가이드")
    parser.add_argument("--pages", default="60-70")
    parser.add_argument("--engines", choices=["twopass", "clova", "all"], default="all")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "ocr_compare")
    args = parser.parse_args()

    run_compare(args.doc, args.pages, args.engines, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

