#!/usr/bin/env python3
"""로컬 환경에서 CLOVA OCR 결과를 채워 넣는 실행 스크립트."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import time

from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parser.clova_ocr import ClovaOcrError, clova_ocr_page

HEADER_KEYWORDS = ["수술종수", "수술명", "수술해설", "종수", "분류"]


def parse_pages(value: str) -> list[int]:
    """페이지 인수 문자열을 0-index 리스트로 파싱한다."""

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
        else:
            pages.append(int(token))
    return sorted(set(pages))


def _block_quality(block_dict: dict) -> dict:
    text = str(block_dict.get("text", "") or "")
    chars = len(text.replace(" ", "").replace("\n", ""))
    if chars == 0:
        return {"chars": 0, "korean_ratio": 0.0, "noise_ratio": 0.0, "grade": "FAIL"}

    korean = len(re.findall(r"[가-힣]", text))
    noise = len(re.findall(r"[^\w\s가-힣\.\,\!\?\:\;\-\(\)\[\]\{\}\/\\\|\@\#\$\%\^\&\*\+\=\'\"\`\~]", text))
    korean_ratio = korean / chars
    noise_ratio = noise / chars

    if korean_ratio >= 0.5 and noise_ratio <= 0.05:
        grade = "PASS"
    elif korean_ratio >= 0.3 or noise_ratio <= 0.1:
        grade = "MARGINAL"
    else:
        grade = "FAIL"

    return {
        "chars": chars,
        "korean_ratio": round(korean_ratio, 3),
        "noise_ratio": round(noise_ratio, 3),
        "grade": grade,
    }


def _header_score(table_json: dict) -> float:
    headers = table_json.get("headers", []) if isinstance(table_json, dict) else []
    if not headers:
        return 0.0
    matched = sum(1 for header in headers if any(keyword in str(header) for keyword in HEADER_KEYWORDS))
    return round(matched / len(headers), 3)


def _safe_average(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _normalize_table_json(table_json: dict | None) -> dict | None:
    if table_json is None:
        return None
    headers = [str(value) for value in table_json.get("headers", [])]
    rows: list[dict] = []
    for row in table_json.get("rows", []):
        if isinstance(row, dict):
            rows.append({str(key): str(value) for key, value in row.items()})
        else:
            values = [str(value) for value in row]
            padded = values + [""] * max(0, len(headers) - len(values))
            rows.append(dict(zip(headers, padded[: len(headers)])))
    return {"headers": headers, "rows": rows}


def _build_metrics(blocks: list[dict], figure_blocks: int = 0) -> dict:
    table_blocks = sum(1 for block in blocks if block.get("block_type") == "table")
    text_blocks = sum(1 for block in blocks if block.get("block_type") in {"text", "title"})

    korean_ratios: list[float] = []
    noise_ratios: list[float] = []
    grades = {"PASS": 0, "MARGINAL": 0, "FAIL": 0}
    header_scores: list[float] = []

    for block in blocks:
        quality = block.get("quality", {})
        if quality:
            korean_ratios.append(float(quality.get("korean_ratio", 0.0)))
            noise_ratios.append(float(quality.get("noise_ratio", 0.0)))
            grade = str(quality.get("grade", ""))
            if grade in grades:
                grades[grade] += 1

        if block.get("block_type") == "table":
            header_scores.append(_header_score(block.get("table_json") or {}))

    return {
        "total_blocks": len(blocks),
        "table_blocks": table_blocks,
        "text_blocks": text_blocks,
        "figure_blocks": figure_blocks,
        "avg_korean_ratio": _safe_average(korean_ratios),
        "avg_noise_ratio": _safe_average(noise_ratios),
        "grade_pass": grades["PASS"],
        "grade_marginal": grades["MARGINAL"],
        "grade_fail": grades["FAIL"],
        "header_score_avg": _safe_average(header_scores),
    }


def _load_hybrid_context(doc_dir: Path, page_no: int) -> tuple[str, list[dict]]:
    default_masked = f"p{page_no:03d}_masked.png"
    hybrid_path = doc_dir / f"p{page_no:03d}_hybrid.json"
    if not hybrid_path.exists():
        return default_masked, []
    try:
        payload = json.loads(hybrid_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_masked, []
    masked = str(payload.get("masked_image", default_masked))
    figures = payload.get("figures", [])
    return masked, figures if isinstance(figures, list) else []


def _serialize_blocks(blocks) -> list[dict]:
    serialized: list[dict] = []
    for block in blocks:
        raw = asdict(block)
        entry = {
            "block_type": raw.get("block_type"),
            "bbox": [int(v) for v in raw.get("bbox", [])],
            "text": raw.get("text", ""),
            "table_json": _normalize_table_json(raw.get("table_json")),
            "source_method": raw.get("source_method", "ocr_clova"),
            "raw": raw.get("raw", {}),
        }
        entry["quality"] = _block_quality(entry)
        serialized.append(entry)
    return serialized


def _write_page_json(
    *,
    doc_short: str,
    doc_dir: Path,
    page_no: int,
    elapsed_sec: float,
    masked_image: str,
    figures: list[dict],
    status: str,
    error: str | None,
    blocks: list[dict],
) -> dict:
    metrics = _build_metrics(blocks, figure_blocks=0 if status != "SUCCESS" else len(figures))
    payload = {
        "engine": "clova",
        "doc_short": doc_short,
        "page_no": page_no,
        "elapsed_sec": round(elapsed_sec, 3),
        "status": status,
        "error": error,
        "original_image": f"p{page_no:03d}_original.png",
        "masked_image": masked_image,
        "figures": figures,
        "blocks": blocks,
        "metrics": metrics,
    }
    output_path = doc_dir / f"p{page_no:03d}_clova.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _update_summary(output_dir: Path, doc_short: str, clova_results: list[dict], engine_key: str = "clova") -> None:
    summary_path = output_dir / doc_short / "summary.json"
    if not summary_path.exists():
        return

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    success = [result for result in clova_results if result.get("status") == "SUCCESS"]
    skipped_pages = [int(result["page_no"]) for result in clova_results if result.get("status") == "SKIPPED"]

    avg_elapsed = (sum(float(result["elapsed_sec"]) for result in success) / len(success)) if success else None
    all_blocks = [block for result in success for block in result.get("blocks", [])]
    table_blocks = [block for block in all_blocks if block.get("block_type") == "table"]

    korean_ratios = [float(block.get("quality", {}).get("korean_ratio", 0.0)) for block in all_blocks if block.get("quality")]
    avg_korean_ratio = (sum(korean_ratios) / len(korean_ratios)) if korean_ratios else None

    noise_ratios = [float(block.get("quality", {}).get("noise_ratio", 0.0)) for block in all_blocks if block.get("quality")]
    avg_noise_ratio = (sum(noise_ratios) / len(noise_ratios)) if noise_ratios else None

    header_scores = [float(result.get("metrics", {}).get("header_score_avg", 0.0)) for result in success]
    avg_header = (sum(header_scores) / len(header_scores)) if header_scores else None

    grades = {"PASS": 0, "MARGINAL": 0, "FAIL": 0}
    for block in all_blocks:
        grade = block.get("quality", {}).get("grade", "")
        if grade in grades:
            grades[grade] += 1

    summary.setdefault("engines", {})
    summary["engines"][engine_key] = {
        "avg_elapsed_sec": round(avg_elapsed, 3) if avg_elapsed is not None else None,
        "avg_korean_ratio": round(avg_korean_ratio, 3) if avg_korean_ratio is not None else None,
        "avg_noise_ratio": round(avg_noise_ratio, 3) if avg_noise_ratio is not None else None,
        "table_blocks": len(table_blocks),
        "header_score_avg": round(avg_header, 3) if avg_header is not None else None,
        "grade": grades,
        "skipped_pages": skipped_pages,
        "status": "SUCCESS" if not skipped_pages else ("PARTIAL" if success else "SKIPPED"),
    }
    timestamp_key = "clova_rerun_at" if engine_key == "clova" else f"{engine_key}_run_at"
    summary[timestamp_key] = datetime.now().isoformat(timespec="seconds")

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[run_clova_local] summary.json {engine_key} 업데이트 완료")


def run_clova_local(
    doc_short: str,
    pages_arg: str,
    output_dir: Path,
    timeout_sec: int,
    vision_clean: bool = False,
) -> None:
    doc_dir = output_dir / doc_short
    if not doc_dir.exists():
        raise FileNotFoundError(f"결과 디렉터리를 찾을 수 없습니다: {doc_dir}")

    pages = parse_pages(pages_arg)
    if not pages:
        raise ValueError("처리할 페이지가 없습니다.")

    results: list[dict] = []
    success = skipped = 0
    total_started = time.perf_counter()
    vision_client = None
    clean_table_blocks = None
    refine_numeric_cells = None
    if vision_clean:
        import openai

        from src.parser.numeric_cell_refiner import refine_numeric_cells as refine_numeric_cells_func
        from src.parser.table_vision_cleaner import clean_table_blocks as clean_table_blocks_func

        vision_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        clean_table_blocks = clean_table_blocks_func
        refine_numeric_cells = refine_numeric_cells_func

    for page_no in pages:
        original_path = doc_dir / f"p{page_no:03d}_original.png"
        if not original_path.exists():
            elapsed = 0.0
            masked_image, figures = _load_hybrid_context(doc_dir, page_no)
            result = _write_page_json(
                doc_short=doc_short,
                doc_dir=doc_dir,
                page_no=page_no,
                elapsed_sec=elapsed,
                masked_image=masked_image,
                figures=figures,
                status="SKIPPED",
                error=f"원본 이미지 파일이 없습니다: {original_path.name}",
                blocks=[],
            )
            results.append(result)
            skipped += 1
            print(f"[run_clova_local] p{page_no:03d} -> SKIPPED (원본 이미지 없음)")
            continue

        masked_image, figures = _load_hybrid_context(doc_dir, page_no)
        started = time.perf_counter()
        try:
            with Image.open(original_path) as image:
                image.load()
                blocks = clova_ocr_page(image, page_name=f"p{page_no:03d}", timeout_sec=timeout_sec)
                if clean_table_blocks is not None:
                    blocks = clean_table_blocks(blocks, image, vision_client)
                if refine_numeric_cells is not None:
                    blocks = refine_numeric_cells(blocks, image, vision_client)
            block_payload = _serialize_blocks(blocks)
            elapsed = time.perf_counter() - started
            result = _write_page_json(
                doc_short=doc_short,
                doc_dir=doc_dir,
                page_no=page_no,
                elapsed_sec=elapsed,
                masked_image=masked_image,
                figures=figures,
                status="SUCCESS",
                error=None,
                blocks=block_payload,
            )
            results.append(result)
            success += 1
            print(f"[run_clova_local] p{page_no:03d} -> SUCCESS ({len(block_payload)}블록, {elapsed:.1f}초)")
        except ClovaOcrError as exc:
            elapsed = time.perf_counter() - started
            result = _write_page_json(
                doc_short=doc_short,
                doc_dir=doc_dir,
                page_no=page_no,
                elapsed_sec=elapsed,
                masked_image=masked_image,
                figures=figures,
                status="SKIPPED",
                error=str(exc),
                blocks=[],
            )
            results.append(result)
            skipped += 1
            print(f"[run_clova_local] p{page_no:03d} -> SKIPPED ({exc})")

    _update_summary(output_dir, doc_short, results)
    total_elapsed = time.perf_counter() - total_started
    print("=== 완료 ===")
    print(f"SUCCESS: {success}/{len(pages)} | SKIPPED: {skipped}/{len(pages)} | 총 소요: {total_elapsed:.1f}초")
    print(f"저장 위치: {doc_dir}")


def main() -> int:
    load_dotenv(Path(__file__).parent.parent / ".env")

    parser = argparse.ArgumentParser(description="로컬 CLOVA OCR 결과 채우기")
    parser.add_argument("--doc", default="실무가이드")
    parser.add_argument("--pages", default="60-70")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "ocr_compare")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--vision-clean",
        action="store_true",
        default=False,
        help="OpenAI Vision LLM으로 표 셀 그림 감지 및 OCR 보정",
    )
    args = parser.parse_args()

    run_clova_local(args.doc, args.pages, args.output_dir, args.timeout, vision_clean=args.vision_clean)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
