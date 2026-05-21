#!/usr/bin/env python3
"""상담사례집 v1의 지정 16페이지 block type을 v2 규칙으로 맞춰 재청킹 산출물을 만든다."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_PAGES = [22, 39, 49, 57, 67, 73, 93, 96, 114, 117, 137, 147, 247, 283, 294, 308]


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _patch_manifest(v1_manifest_path: Path, v2_manifest_path: Path, in_place: bool) -> dict[int, dict[str, int]]:
    v1 = _load_json(v1_manifest_path)
    v2 = _load_json(v2_manifest_path)
    v2_pages = {int(page["page_no"]): page for page in v2.get("pages", [])}
    report: dict[int, dict[str, int]] = {}

    for page in v1.get("pages", []):
        page_no = int(page.get("page_no", -1))
        page_label = page_no + 1
        if page_label not in TARGET_PAGES:
            continue
        src = v2_pages.get(page_no)
        if src is None:
            continue

        before = Counter(str(block.get("type", "text")) for block in page.get("blocks", []))
        src_blocks = src.get("blocks", [])
        dst_blocks = page.get("blocks", [])

        for index, dst_block in enumerate(dst_blocks):
            if index >= len(src_blocks):
                break
            dst_block["type"] = src_blocks[index].get("type", dst_block.get("type", "text"))

        after = Counter(str(block.get("type", "text")) for block in page.get("blocks", []))
        report[page_label] = {
            "before_text": before.get("text", 0),
            "before_table": before.get("table", 0),
            "after_text": after.get("text", 0),
            "after_table": after.get("table", 0),
        }

    if in_place:
        _save_json(v1_manifest_path, v1)
        print(f"[patch] V1 manifest updated in-place: {v1_manifest_path}")
    else:
        print("[patch] V1 manifest not updated (dry-run). Use --in-place to save changes.")
    return report


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _save_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _merge_chunks(v1_chunks_path: Path, rechunked_chunks_path: Path, output_chunks_path: Path) -> tuple[int, int, int]:
    original = _load_jsonl(v1_chunks_path)
    rechunked = _load_jsonl(rechunked_chunks_path)

    replacement_pages = set(TARGET_PAGES)
    original_kept: list[dict] = []
    replaced_counter = 0
    for row in original:
        meta = row.get("metadata", {})
        if meta.get("doc_short") == "상담사례집" and int(meta.get("page_start", 0) or 0) in replacement_pages:
            replaced_counter += 1
            continue
        original_kept.append(row)

    inserted = 0
    by_page = defaultdict(list)
    for row in rechunked:
        meta = row.get("metadata", {})
        if meta.get("doc_short") == "상담사례집":
            page = int(meta.get("page_start", 0) or 0)
            if page in replacement_pages:
                by_page[page].append(row)

    merged = list(original_kept)
    for page in TARGET_PAGES:
        chunks = by_page.get(page, [])
        inserted += len(chunks)
        merged.extend(chunks)

    _save_jsonl(output_chunks_path, merged)
    return replaced_counter, inserted, len(merged)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rechunk target 16 pages of 상담사례집 v1")
    parser.add_argument("--extracted-v1-root", type=Path, default=ROOT / "data" / "extracted_v1_rechunked")
    parser.add_argument("--extracted-v2-root", type=Path, default=ROOT / "data" / "extracted_v2_manual")
    parser.add_argument("--v1-chunks", type=Path, default=ROOT / "data" / "processed" / "chunks_v1_original_ocr.jsonl")
    parser.add_argument("--rechunked-chunks", type=Path, default=ROOT / "data" / "processed" / "chunks_v1_rechunked_only_sangdam.jsonl")
    parser.add_argument("--output-chunks", type=Path, default=ROOT / "data" / "processed" / "chunks_v1_rechunked_target16.jsonl")
    parser.add_argument("--in-place", action="store_true", help="V1 manifest를 실제로 수정하여 덮어씁니다.")
    args = parser.parse_args()

    v1_root = args.extracted_v1_root if args.extracted_v1_root.is_absolute() else ROOT / args.extracted_v1_root
    v2_root = args.extracted_v2_root if args.extracted_v2_root.is_absolute() else ROOT / args.extracted_v2_root
    v1_chunks = args.v1_chunks if args.v1_chunks.is_absolute() else ROOT / args.v1_chunks
    rechunked_chunks = args.rechunked_chunks if args.rechunked_chunks.is_absolute() else ROOT / args.rechunked_chunks
    output_chunks = args.output_chunks if args.output_chunks.is_absolute() else ROOT / args.output_chunks

    if not v1_root.exists():
        raise SystemExit(f"Error: V1 extracted root directory does not exist: {v1_root}")
    if not v2_root.exists():
        raise SystemExit(f"Error: V2 extracted root directory does not exist: {v2_root}")

    v1_manifest_path = v1_root / "상담사례집" / "manifest.json"
    v2_manifest_path = v2_root / "상담사례집" / "manifest.json"

    if not v1_manifest_path.exists():
        raise SystemExit(f"Error: V1 manifest file not found: {v1_manifest_path}")
    if not v2_manifest_path.exists():
        raise SystemExit(f"Error: V2 manifest file not found: {v2_manifest_path}")

    report = _patch_manifest(v1_manifest_path, v2_manifest_path, args.in_place)
    print("[patch] block type update summary:")
    for page in TARGET_PAGES:
        r = report.get(page)
        if not r:
            print(f"  p{page:03d}: no change")
            continue
        print(
            f"  p{page:03d}: text/table {r['before_text']}/{r['before_table']} -> "
            f"{r['after_text']}/{r['after_table']}"
        )

    print("[next] run ingest chunks for patched root:")
    print(
        f"python scripts/ingest.py --include-ocr --stage chunks "
        f"--extracted-root {v1_root} "
        f"--chunks-path {rechunked_chunks}"
    )

    if rechunked_chunks.exists():
        replaced, inserted, total = _merge_chunks(v1_chunks, rechunked_chunks, output_chunks)
        print(f"[merge] replaced chunks: {replaced}")
        print(f"[merge] inserted chunks: {inserted}")
        print(f"[merge] output total chunks: {total}")
        print(f"[merge] output: {output_chunks}")
    else:
        print(f"[merge] Warning: rechunked source chunks file not found: {rechunked_chunks}. Merging skipped.")


if __name__ == "__main__":
    main()
