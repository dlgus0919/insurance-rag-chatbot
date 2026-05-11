#!/usr/bin/env python3
"""전체 스캔 PDF True Hybrid OCR 실행 및 data/extracted 포맷 저장."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.parser.clova_ocr import ClovaOcrError, clova_ocr_page
from src.parser.numeric_cell_refiner import NumericCellRefinerAuthError, refine_numeric_cells
from src.parser.ocr_engine import LayoutBlock, run_ppstructure
from src.parser.pdf_extractor import extract_page_image, get_page_count
from src.parser.table_vision_cleaner import TableVisionCleanerAuthError, clean_table_blocks

DEFAULT_OUTPUT_DIR = ROOT / "data" / "extracted"
TRUE_HYBRID_ENGINE = "true_hybrid"


def parse_pages(value: str | None, total_pages: int) -> list[int]:
    """페이지 인수 문자열을 0-indexed 페이지 리스트로 변환한다."""

    if value is None:
        return list(range(total_pages))

    pages: list[int] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError(f"잘못된 페이지 범위입니다: {token}")
            pages.extend(range(start, end + 1))
            continue
        pages.append(int(token))

    unique_pages = sorted(set(pages))
    invalid = [page for page in unique_pages if page < 0 or page >= total_pages]
    if invalid:
        raise ValueError(f"페이지 범위를 벗어났습니다: {invalid[:5]} / total_pages={total_pages}")
    return unique_pages


def _load_manifest(manifest_path: Path, doc_short: str, total_pages: int) -> dict:
    if not manifest_path.exists():
        return {"doc_short": doc_short, "total_pages": total_pages, "pages": []}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["doc_short"] = manifest.get("doc_short") or doc_short
    manifest["total_pages"] = int(manifest.get("total_pages") or total_pages)
    manifest.setdefault("pages", [])
    return manifest


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(manifest_path)


def _is_page_done(manifest: dict, page_no: int) -> bool:
    """manifest에 해당 페이지의 true_hybrid 성공 결과가 있으면 True."""

    for page_info in manifest.get("pages", []):
        if int(page_info.get("page_no", -1)) == page_no and page_info.get("engine") == TRUE_HYBRID_ENGINE:
            return True
    return False


def _table_to_text(table_json: dict) -> str:
    headers = [str(value) for value in table_json.get("headers", [])]
    lines: list[str] = []
    if headers:
        lines.append(" | ".join(headers))
    for row in table_json.get("rows", []):
        if isinstance(row, dict):
            values = [str(row.get(header, "")) for header in headers]
        else:
            values = [str(value) for value in row]
        lines.append(" | ".join(values))
    return "\n".join(lines)


def _normalize_table_json(table_json: dict | None) -> dict | None:
    if not isinstance(table_json, dict):
        return None
    headers = [str(value) for value in table_json.get("headers", [])]
    rows: list[dict] = []
    for row in table_json.get("rows", []):
        if isinstance(row, dict):
            rows.append({str(key): str(value) for key, value in row.items()})
            continue
        values = [str(value) for value in row]
        padded = values + [""] * max(0, len(headers) - len(values))
        rows.append(dict(zip(headers, padded[: len(headers)])))
    if not headers and not rows:
        return None
    return {"headers": headers, "rows": rows}


def _block_bbox(block: LayoutBlock) -> list[int]:
    return [int(round(float(value))) for value in (block.bbox or [])[:4]]


def _block_confidence(block: LayoutBlock) -> float:
    try:
        return float(block.confidence if block.confidence is not None else 1.0)
    except (TypeError, ValueError):
        return 1.0


def _save_blocks(blocks: list[LayoutBlock], out_dir: Path, page_no: int) -> list[dict]:
    """LayoutBlock 목록을 data/extracted 블록 파일과 manifest entry로 저장한다."""

    text_dir = out_dir / "text"
    table_dir = out_dir / "tables"
    text_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)

    block_entries: list[dict] = []
    text_index = 0
    table_index = 0

    for block in blocks:
        if block.block_type == "figure":
            continue

        if block.block_type == "table":
            table_json = _normalize_table_json(block.table_json)
            if table_json is None:
                continue
            text = _table_to_text(table_json).strip()
            if not text:
                continue

            stem = f"p{page_no:03d}_t{table_index:02d}"
            text_path = table_dir / f"{stem}.txt"
            json_path = table_dir / f"{stem}.json"
            text_path.write_text(text, encoding="utf-8")
            json_path.write_text(json.dumps(table_json, ensure_ascii=False, indent=2), encoding="utf-8")

            raw = block.raw or {}
            entry = {
                "type": "table",
                "file": f"tables/{stem}.txt",
                "bbox": _block_bbox(block),
                "confidence": _block_confidence(block),
                "chars": len(text),
                "vision_cleaned": bool(raw.get("vision_cleaned", False)),
                "numeric_refined": bool(raw.get("numeric_refined", False)),
            }
            if raw.get("numeric_corrections"):
                entry["numeric_corrections"] = raw["numeric_corrections"]
            if raw.get("numeric_unresolved_cells"):
                entry["numeric_unresolved_cells"] = raw["numeric_unresolved_cells"]
            block_entries.append(entry)
            table_index += 1
            continue

        text = str(block.text or "").strip()
        if not text:
            continue
        stem = f"p{page_no:03d}_b{text_index:02d}"
        text_path = text_dir / f"{stem}.txt"
        text_path.write_text(text, encoding="utf-8")
        block_entries.append(
            {
                "type": "text",
                "file": f"text/{stem}.txt",
                "bbox": _block_bbox(block),
                "confidence": _block_confidence(block),
                "chars": len(text),
            }
        )
        text_index += 1

    return block_entries


def _update_manifest(
    manifest_path: Path,
    manifest: dict,
    page_no: int,
    page_label: int,
    block_entries: list[dict],
) -> dict:
    """단일 페이지 manifest 항목을 교체하고 즉시 저장한다."""

    page_entry = {
        "page_no": page_no,
        "page_label": page_label,
        "engine": TRUE_HYBRID_ENGINE,
        "fallback_reason": None,
        "blocks": block_entries,
    }
    pages = [page for page in manifest.get("pages", []) if int(page.get("page_no", -1)) != page_no]
    pages.append(page_entry)
    pages.sort(key=lambda page: int(page.get("page_no", 0)))
    manifest["pages"] = pages
    _write_manifest(manifest_path, manifest)
    return page_entry


def _is_clova_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "401" in text or "unauthorized" in text or "인증" in text


def _layout_regions(blocks: list[LayoutBlock]) -> list[LayoutBlock]:
    return [block for block in blocks if block.block_type != "figure"]


def _apply_vision_cleaning(
    blocks: list[LayoutBlock],
    image: Any,
    vision_client: Any,
    numeric_model: str,
) -> tuple[list[LayoutBlock], bool]:
    """Vision 정제를 적용한다. OpenAI 인증 실패 시 비활성화를 요청한다."""

    try:
        cleaned = clean_table_blocks(blocks, image, vision_client)
        refined = refine_numeric_cells(cleaned, image, vision_client, model=numeric_model)
        return refined, True
    except (TableVisionCleanerAuthError, NumericCellRefinerAuthError) as exc:
        print(f"[run_full_ocr] OpenAI 인증 오류: {exc}. --vision-clean을 비활성화하고 계속합니다.")
        return blocks, False


def _process_page(
    pdf_path: Path,
    page_no: int,
    out_dir: Path,
    *,
    timeout_sec: int,
    vision_client: Any = None,
    numeric_model: str = "gpt-4.1",
) -> tuple[list[dict], bool]:
    """단일 페이지를 True Hybrid OCR로 처리하고 블록 파일을 저장한다."""

    image = extract_page_image(pdf_path, page_no)
    pp_blocks = run_ppstructure(image)
    blocks = clova_ocr_page(
        image,
        page_name=f"p{page_no:03d}",
        layout_regions=_layout_regions(pp_blocks),
        timeout_sec=timeout_sec,
    )

    vision_available = True
    if vision_client is not None and any(block.block_type == "table" for block in blocks):
        blocks, vision_available = _apply_vision_cleaning(blocks, image, vision_client, numeric_model)

    return _save_blocks(blocks, out_dir, page_no), vision_available


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _select_sources(doc: str) -> list[config.PdfSource]:
    ocr_sources = [source for source in config.PDF_SOURCES if source.requires_ocr]
    if doc == "all":
        return ocr_sources
    selected = [source for source in ocr_sources if source.doc_short == doc]
    if not selected:
        choices = ", ".join(source.doc_short for source in ocr_sources)
        raise ValueError(f"OCR 대상 문서를 찾을 수 없습니다: {doc} (가능: {choices}, all)")
    return selected


def _confirm_vision_clean(vision_clean: bool, yes: bool) -> None:
    if not vision_clean:
        return
    print("[경고] --vision-clean 활성화: 표 감지 페이지마다 OpenAI Vision API를 2회 호출합니다.")
    print("       전체 실행 시 추가 비용이 발생할 수 있습니다. 계속하려면 Enter를 누르세요.")
    if yes or os.getenv("CI", "").lower() == "true":
        return
    input()


def run_document(
    source: config.PdfSource,
    *,
    pages_arg: str | None,
    output_dir: Path,
    force: bool,
    timeout_sec: int,
    vision_clean: bool,
    vision_client: Any = None,
    numeric_model: str = "gpt-4.1",
) -> dict:
    total_pages = get_page_count(source.path)
    pages = parse_pages(pages_arg, total_pages)
    doc_dir = output_dir / source.doc_short
    manifest_path = doc_dir / "manifest.json"
    manifest = _load_manifest(manifest_path, source.doc_short, total_pages)

    print(f"[run_full_ocr] {source.doc_short} ({total_pages} 페이지) 시작")
    success = skipped = failed = 0
    started_all = time.perf_counter()
    vision_available = vision_clean

    for completed, page_no in enumerate(pages, start=1):
        page_name = f"p{page_no:03d}"
        if not force and _is_page_done(manifest, page_no):
            skipped += 1
            print(f"[run_full_ocr] {page_name} -> SKIPPED (기존 true_hybrid 결과)  [{completed}/{len(pages)} 완료]")
            continue

        started = time.perf_counter()
        try:
            active_vision_client = vision_client if vision_available else None
            block_entries, page_vision_available = _process_page(
                source.path,
                page_no,
                doc_dir,
                timeout_sec=timeout_sec,
                vision_client=active_vision_client,
                numeric_model=numeric_model,
            )
            if not page_vision_available:
                vision_available = False
            elapsed = time.perf_counter() - started
            _update_manifest(manifest_path, manifest, page_no, page_no + 1, block_entries)
            success += 1
            print(
                f"[run_full_ocr] {page_name} -> SUCCESS ({len(block_entries)}블록, {elapsed:.1f}초)  "
                f"[{completed}/{len(pages)} 완료]"
            )
        except ClovaOcrError as exc:
            if _is_clova_auth_error(exc):
                raise
            failed += 1
            print(f"[run_full_ocr] {page_name} -> FAILED: {exc}  [{completed}/{len(pages)} 완료]")
        except (TableVisionCleanerAuthError, NumericCellRefinerAuthError) as exc:
            vision_available = False
            failed += 1
            print(
                f"[run_full_ocr] {page_name} -> FAILED: OpenAI auth during vision clean ({exc})  "
                f"[{completed}/{len(pages)} 완료]"
            )
        except Exception as exc:
            failed += 1
            print(f"[run_full_ocr] {page_name} -> FAILED: {exc}  [{completed}/{len(pages)} 완료]")

    elapsed_all = time.perf_counter() - started_all
    print(f"=== {source.doc_short} 완료 ===")
    print(
        f"SUCCESS: {success}/{len(pages)} | SKIPPED: {skipped}/{len(pages)} | "
        f"FAILED: {failed}/{len(pages)} | 소요: {_format_elapsed(elapsed_all)}"
    )
    return {"success": success, "skipped": skipped, "failed": failed, "total": len(pages)}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="전체 스캔본 True Hybrid OCR 실행")
    parser.add_argument("--doc", required=True, help="실무가이드, 상담사례집 또는 all")
    parser.add_argument("--pages", default=None, help="0-indexed 페이지 범위. 예: 60-70, 64")
    parser.add_argument("--vision-clean", action="store_true", default=False, help="OpenAI Vision 표/숫자 정제 활성화")
    parser.add_argument("--force", action="store_true", default=False, help="기존 true_hybrid 페이지도 재처리")
    parser.add_argument("--timeout", type=int, default=90, help="페이지당 CLOVA API 타임아웃 초")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--yes", action="store_true", default=False, help="비용 경고 확인을 생략")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    sources = _select_sources(args.doc)
    _confirm_vision_clean(args.vision_clean, args.yes)

    vision_client = None
    numeric_model = os.getenv("OCR_NUMERIC_VISION_MODEL", "gpt-4.1")
    if args.vision_clean:
        import openai

        vision_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    for source in sources:
        run_document(
            source,
            pages_arg=args.pages,
            output_dir=args.output_dir,
            force=args.force,
            timeout_sec=args.timeout,
            vision_clean=args.vision_clean,
            vision_client=vision_client,
            numeric_model=numeric_model,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
