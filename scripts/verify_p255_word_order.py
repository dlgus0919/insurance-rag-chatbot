#!/usr/bin/env python3
"""p255(page_label=255) 단어 순서 검증 스크립트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "extracted" / "실무가이드" / "manifest.json"
TEXT_DIR = ROOT / "data" / "extracted" / "실무가이드" / "text"
TARGET_PAGE_NOS = (254, 255)

# 현재 실제 파일 내용 기준 (2026-05-13)
KNOWN_BAD_PATTERNS = [
    "각각 원칙적으로",
    "기능장해가 다른 생기고",
]

KNOWN_GOOD_PATTERNS = [
    "원칙적으로 각각",
]


@dataclass
class FileCheckResult:
    file: str
    status: str
    detail: str


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_registered_text_blocks(manifest: dict) -> dict[int, list[str]]:
    page_to_files: dict[int, list[str]] = {}
    for page in manifest.get("pages", []):
        page_no = page.get("page_no")
        if page_no not in TARGET_PAGE_NOS:
            continue
        files: list[str] = []
        for block in page.get("blocks", []):
            if block.get("type") == "text" and block.get("file"):
                files.append(block["file"])
        page_to_files[page_no] = files
    return page_to_files


def _read_text_file(rel_file: str) -> str:
    path = ROOT / "data" / "extracted" / "실무가이드" / rel_file
    return path.read_text(encoding="utf-8")


def _short_preview(text: str, limit: int = 48) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _check_file(rel_file: str) -> FileCheckResult:
    text = _read_text_file(rel_file)

    bad_hits = [pattern for pattern in KNOWN_BAD_PATTERNS if pattern in text]
    if bad_hits:
        return FileCheckResult(
            file=rel_file,
            status="FAIL",
            detail=f'BAD ORDER DETECTED: {", ".join(bad_hits)}',
        )

    good_hits = [pattern for pattern in KNOWN_GOOD_PATTERNS if pattern in text]
    if good_hits:
        return FileCheckResult(
            file=rel_file,
            status="PASS",
            detail=f'GOOD ORDER CONFIRMED: {", ".join(good_hits)}',
        )

    return FileCheckResult(
        file=rel_file,
        status="WARN",
        detail=f'no known pattern hit; preview="{_short_preview(text)}"',
    )


def _collect_registered_set(manifest: dict) -> set[str]:
    files: set[str] = set()
    for page in manifest.get("pages", []):
        for block in page.get("blocks", []):
            rel_file = block.get("file")
            if rel_file:
                files.add(rel_file)
    return files


def _find_stale_text_files(registered: set[str]) -> list[str]:
    stale: list[str] = []
    for path in sorted(TEXT_DIR.glob("*.txt")):
        rel = f"text/{path.name}"
        if rel not in registered:
            stale.append(rel)
    return stale


def main() -> int:
    manifest = _load_manifest(MANIFEST_PATH)
    page_to_files = _collect_registered_text_blocks(manifest)
    registered = _collect_registered_set(manifest)
    stale = _find_stale_text_files(registered)

    print("=== p255 Word Order Verification ===")

    status_counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    total_checked = 0

    page_lookup = {page.get("page_no"): page for page in manifest.get("pages", [])}
    for page_no in TARGET_PAGE_NOS:
        page = page_lookup.get(page_no, {})
        print(f"Checking page_no={page_no} (page_label={page.get('page_label')}):")
        files = page_to_files.get(page_no, [])
        if not files:
            print("  [WARN] no registered text blocks")
            status_counts["WARN"] += 1
            continue

        for rel_file in files:
            result = _check_file(rel_file)
            status_counts[result.status] += 1
            total_checked += 1
            if result.status == "PASS":
                print(f"  [PASS] {result.file} — {result.detail}")
            elif result.status == "FAIL":
                print(f"  [FAIL] {result.file} — {result.detail}")
            else:
                print(f"  [WARN] {result.file} — {result.detail}")

    print("")
    print("Stale text files (not in manifest):")
    if stale:
        for rel_file in stale:
            text = _read_text_file(rel_file)
            bad_hits = [pattern for pattern in KNOWN_BAD_PATTERNS if pattern in text]
            marker = " BAD ORDER DETECTED" if bad_hits else ""
            print(f"  [STALE] {rel_file} — preview=\"{_short_preview(text)}\"{marker}")
    else:
        print("  (none)")

    overall = "FAIL" if status_counts["FAIL"] > 0 else "PASS"
    print("")
    print("Summary:")
    print(f"  Registered blocks checked: {total_checked}")
    print(f"  PASS: {status_counts['PASS']} | WARN: {status_counts['WARN']} | FAIL: {status_counts['FAIL']}")
    print(f"  Stale files: {len(stale)}")
    print(f"  Overall: {overall}")

    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
