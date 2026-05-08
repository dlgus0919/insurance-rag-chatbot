#!/usr/bin/env python3
"""스캔 PDF를 구조화 OCR 추출물로 전처리한다."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.parser.ocr_engine import (
    LayoutBlock,
    _table_html_to_json,
    run_easyocr_fallback,
    run_ppstructure,
    should_use_easyocr_fallback,
)
from src.parser.ocr_postprocess import normalize_ocr_text
from src.parser.pdf_extractor import extract_page_image, get_page_count

EXTRACTED_BASE = ROOT / "data" / "extracted"


def parse_pages_arg(value: str | None, total_pages: int) -> list[int]:
    """CLI 페이지 지정값을 0-indexed 페이지 목록으로 변환한다."""

    if value is None:
        return list(range(total_pages))

    pages: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start = int(start_str)
            end = int(end_str)
            if end < start:
                raise ValueError(f"페이지 범위가 역순입니다: {part}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))

    deduped = sorted(set(pages))
    invalid = [page for page in deduped if page < 0 or page >= total_pages]
    if invalid:
        raise ValueError(f"페이지가 문서 범위를 벗어났습니다: {invalid[:5]} / total={total_pages}")
    return deduped


def ensure_output_dirs(out_dir: Path) -> None:
    for name in ("text", "tables", "images"):
        (out_dir / name).mkdir(parents=True, exist_ok=True)


def manifest_content_type(block_type: str) -> str:
    if block_type == "table":
        return "table"
    if block_type == "figure":
        return "figure"
    return "text"


def _safe_bbox(bbox: list[int], width: int, height: int) -> tuple[int, int, int, int] | None:
    if len(bbox) != 4:
        return None
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(width, int(x1)))
    x2 = max(0, min(width, int(x2)))
    y1 = max(0, min(height, int(y1)))
    y2 = max(0, min(height, int(y2)))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _run_primary_or_fallback(
    image,
    fallback_engine: str,
    fallback_threshold: float,
) -> tuple[str, list[LayoutBlock], str | None]:
    fallback_reason: str | None = None
    try:
        blocks = run_ppstructure(image)
    except Exception as exc:  # pragma: no cover - 실제 PP-Structure 환경 의존
        blocks = []
        fallback_reason = f"ppstructure_error: {exc.__class__.__name__}: {exc}"

    if fallback_engine == "easyocr" and (fallback_reason or should_use_easyocr_fallback(blocks, fallback_threshold)):
        if fallback_reason is None:
            fallback_reason = f"ppstructure_low_confidence_below_{fallback_threshold}"
        return "easyocr", run_easyocr_fallback(image), fallback_reason

    return "ppstructure", blocks, fallback_reason


def process_page(
    pdf_path: Path,
    page_no: int,
    out_dir: Path,
    fallback_engine: str = "easyocr",
    fallback_threshold: float = 0.5,
) -> dict:
    """단일 PDF 페이지를 구조화 OCR 추출물로 저장하고 페이지 메타를 반환한다."""

    ensure_output_dirs(out_dir)
    image = extract_page_image(pdf_path, page_no)
    engine_used, blocks, fallback_reason = _run_primary_or_fallback(image, fallback_engine, fallback_threshold)
    page_meta = {
        "page_no": page_no,
        "page_label": page_no + 1,
        "engine": engine_used,
        "fallback_reason": fallback_reason,
        "blocks": [],
    }

    text_i = table_i = figure_i = 0
    for block in blocks:
        block_type = manifest_content_type(block.block_type)
        text = normalize_ocr_text(block.text)

        if block_type == "table":
            prefix = f"p{page_no:03d}_t{table_i:02d}"
            html = block.html or ""
            table_json = _table_html_to_json(html) if html else {"headers": [], "rows": []}
            if block.raw.get("cell_bbox"):
                table_json["cell_bbox"] = block.raw["cell_bbox"]
            if not text and table_json.get("headers"):
                text = " | ".join(table_json["headers"])
            (out_dir / "tables" / f"{prefix}.html").write_text(html, encoding="utf-8")
            (out_dir / "tables" / f"{prefix}.json").write_text(
                json.dumps(table_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (out_dir / "tables" / f"{prefix}_text.txt").write_text(text, encoding="utf-8")
            page_meta["blocks"].append(
                {
                    "type": "table",
                    "file": f"tables/{prefix}_text.txt",
                    "html_file": f"tables/{prefix}.html",
                    "json_file": f"tables/{prefix}.json",
                    "bbox": block.bbox,
                    "confidence": block.confidence,
                    "chars": len(text),
                }
            )
            table_i += 1
            continue

        if block_type == "figure":
            bbox = _safe_bbox(block.bbox, image.width, image.height)
            if bbox is None:
                continue
            prefix = f"p{page_no:03d}_f{figure_i:02d}"
            cropped = image.crop(bbox)
            cropped.save(str(out_dir / "images" / f"{prefix}.jpg"), "JPEG", quality=90)
            (out_dir / "images" / f"{prefix}_caption.txt").write_text("", encoding="utf-8")
            page_meta["blocks"].append(
                {
                    "type": "figure",
                    "file": f"images/{prefix}.jpg",
                    "caption_file": f"images/{prefix}_caption.txt",
                    "bbox": list(bbox),
                    "confidence": block.confidence,
                }
            )
            figure_i += 1
            continue

        if not text:
            continue
        prefix = f"p{page_no:03d}_b{text_i:02d}"
        (out_dir / "text" / f"{prefix}.txt").write_text(text, encoding="utf-8")
        page_meta["blocks"].append(
            {
                "type": "text",
                "file": f"text/{prefix}.txt",
                "bbox": block.bbox,
                "confidence": block.confidence,
                "chars": len(text),
                "original_type": block.block_type,
            }
        )
        text_i += 1

    return page_meta


def process_document(
    source: config.PdfSource,
    pages: list[int],
    output_base: Path,
    fallback_engine: str,
    fallback_threshold: float,
) -> dict:
    """한 문서의 지정 페이지들을 처리하고 manifest.json을 저장한다."""

    out_dir = output_base / source.doc_short
    ensure_output_dirs(out_dir)
    total_pages = get_page_count(source.path)
    started = time.perf_counter()
    page_metas: list[dict] = []

    print(f"[ocr_extract] {source.doc_short}: {len(pages)}/{total_pages}페이지 처리 시작")
    for page_no in pages:
        page_started = time.perf_counter()
        page_meta = process_page(source.path, page_no, out_dir, fallback_engine, fallback_threshold)
        page_metas.append(page_meta)
        counts = Counter(block["type"] for block in page_meta["blocks"])
        print(
            f"  p{page_no:03d}: engine={page_meta['engine']}, "
            f"text={counts.get('text', 0)}, table={counts.get('table', 0)}, "
            f"figure={counts.get('figure', 0)}, elapsed={time.perf_counter() - page_started:.1f}s"
        )

    engine_stats = Counter(page["engine"] for page in page_metas)
    content_type_stats = Counter(block["type"] for page in page_metas for block in page["blocks"])
    manifest = {
        "doc_short": source.doc_short,
        "doc_name": source.doc_name,
        "pdf_filename": source.path.name,
        "total_pages": total_pages,
        "processed_pages": len(page_metas),
        "page_range": [pages[0], pages[-1]] if pages else [],
        "engine_stats": dict(engine_stats),
        "content_type_stats": dict(content_type_stats),
        "fallback_threshold": fallback_threshold,
        "pages": page_metas,
        "elapsed_sec": round(time.perf_counter() - started, 1),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ocr_extract] manifest 저장: {out_dir / 'manifest.json'}")
    return manifest


def select_targets(doc_short: str | None) -> list[config.PdfSource]:
    targets = [source for source in config.PDF_SOURCES if source.requires_ocr]
    if doc_short:
        targets = [source for source in targets if source.doc_short == doc_short]
        if not targets:
            raise SystemExit(f"OCR 대상 문서를 찾지 못했습니다: {doc_short}")
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description="스캔 PDF OCR 전처리 파이프라인")
    parser.add_argument("--doc", help="처리할 doc_short. 예: 실무가이드")
    parser.add_argument("--pages", help="0-indexed 페이지 범위. 예: 60-70 또는 0,66,132")
    parser.add_argument("--output-dir", type=Path, default=EXTRACTED_BASE)
    parser.add_argument("--fallback-engine", choices=["easyocr", "none"], default="easyocr")
    parser.add_argument("--fallback-threshold", type=float, default=0.5)
    args = parser.parse_args()

    fallback_engine = "none" if args.fallback_engine == "none" else "easyocr"
    for source in select_targets(args.doc):
        if not source.path.exists():
            print(f"[ocr_extract] 파일 없음, 건너뜀: {source.path}")
            continue
        total_pages = get_page_count(source.path)
        pages = parse_pages_arg(args.pages, total_pages)
        process_document(source, pages, args.output_dir, fallback_engine, args.fallback_threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
