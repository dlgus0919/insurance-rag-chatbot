#!/usr/bin/env python3
"""Verify that the configured CLOVA endpoint returns native table data."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parser.clova_ocr import ClovaOcrError, _request_clova


IMAGE_PATH = ROOT / "reports" / "ocr_compare" / "실무가이드" / "p066_original.png"


def _vertices_summary(table: dict) -> str:
    vertices = table.get("boundingPoly", {}).get("vertices", [])
    if not vertices:
        return "[]"
    return json.dumps(vertices, ensure_ascii=False)


def main() -> int:
    load_dotenv(ROOT / ".env")

    if not IMAGE_PATH.exists():
        print(f"[ERROR] image_not_found path={IMAGE_PATH}")
        return 1

    try:
        with Image.open(IMAGE_PATH) as image:
            image.load()
            result = _request_clova(image, page_name="p066_native_table_verify")
    except (OSError, ClovaOcrError) as exc:
        print(f"[ERROR] {exc}")
        return 1

    tables = result.get("tables") or []
    tables_found = len(tables) > 0
    print(f"[RESULT] tables_found={tables_found} count={len(tables)}")
    if tables:
        first = tables[0]
        print(f"[SAMPLE] {len(first.get('cells', []))}cells / bbox={_vertices_summary(first)}")
    else:
        print(f"[RAW] {json.dumps(result, ensure_ascii=False)[:4000]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
