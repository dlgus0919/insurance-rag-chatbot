#!/usr/bin/env python3
"""Generate an HTML comparison viewer for OCR engine outputs."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
ENGINES = ["hybrid", "clova", "true_hybrid"]
ENGINE_LABELS = {
    "hybrid": "Hybrid",
    "clova": "CLOVA",
    "true_hybrid": "True Hybrid",
}


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _discover_pages(doc_dir: Path) -> list[int]:
    pages: set[int] = set()
    for path in doc_dir.glob("p???_*.json"):
        stem = path.stem
        page_text = stem.split("_", 1)[0]
        if page_text.startswith("p") and page_text[1:].isdigit():
            pages.add(int(page_text[1:]))
    return sorted(pages)


def _quality_badge(quality: dict | None) -> str:
    if not quality:
        return ""
    grade = escape(str(quality.get("grade", "")))
    korean = quality.get("korean_ratio", 0.0)
    noise = quality.get("noise_ratio", 0.0)
    return (
        f'<span class="badge grade-{grade.lower()}">{grade}</span>'
        f'<span class="metric">KR {float(korean):.3f}</span>'
        f'<span class="metric">noise {float(noise):.3f}</span>'
    )


def _table_badge(block: dict) -> str:
    raw = block.get("raw") or {}
    if raw.get("native_table") is True:
        return '<span class="badge native">🔵 CLOVA 네이티브</span>'
    return '<span class="badge geometric">🔶 기하학적 재구성</span>'


def _render_table(table_json: dict | None) -> str:
    if not table_json:
        return '<div class="empty">table_json 없음</div>'
    headers = [str(header) for header in table_json.get("headers", [])]
    rows = table_json.get("rows", [])
    if not headers:
        return '<div class="empty">헤더 없음</div>'

    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_rows: list[str] = []
    for row in rows:
        body_rows.append(
            "<tr>"
            + "".join(f"<td>{escape(str(row.get(header, '')))}</td>" for header in headers)
            + "</tr>"
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _render_block(block: dict, index: int) -> str:
    block_type = str(block.get("block_type", "text"))
    bbox = escape(str(block.get("bbox", [])))
    if block_type == "table":
        body = _render_table(block.get("table_json"))
        badge = _table_badge(block)
    else:
        text = escape(str(block.get("text", "")))
        body = f"<pre>{text}</pre>"
        badge = _quality_badge(block.get("quality"))
    return (
        '<section class="block">'
        f'<div class="block-head"><strong>#{index} {escape(block_type)}</strong>'
        f'<span class="bbox">{bbox}</span>{badge}</div>'
        f"{body}</section>"
    )


def _render_engine(payload: dict | None, engine: str) -> str:
    if payload is None:
        return f'<div class="engine missing"><h3>{ENGINE_LABELS[engine]}</h3><p>결과 JSON 없음</p></div>'
    status = escape(str(payload.get("status", "UNKNOWN")))
    error = payload.get("error")
    blocks = payload.get("blocks", [])
    rendered_blocks = "".join(_render_block(block, index + 1) for index, block in enumerate(blocks))
    error_html = f'<pre class="error">{escape(str(error))}</pre>' if error else ""
    return (
        '<div class="engine">'
        f"<h3>{ENGINE_LABELS[engine]}</h3>"
        f'<div class="engine-meta"><span class="badge status">{status}</span>'
        f'<span>{len(blocks)} blocks</span>'
        f'<span>{float(payload.get("elapsed_sec", 0.0)):.2f}s</span></div>'
        f"{error_html}{rendered_blocks}</div>"
    )


def _render_summary(summary: dict | None) -> str:
    if not summary:
        return '<div class="summary"><span>summary.json 없음</span></div>'
    cards: list[str] = []
    for engine in ENGINES:
        stats = (summary.get("engines") or {}).get(engine, {})
        grade = stats.get("grade", {})
        cards.append(
            '<div class="summary-card">'
            f"<h2>{ENGINE_LABELS[engine]}</h2>"
            f'<p>status: <strong>{escape(str(stats.get("status", "N/A")))}</strong></p>'
            f'<p>tables: {escape(str(stats.get("table_blocks", "N/A")))}</p>'
            f'<p>avg KR: {escape(str(stats.get("avg_korean_ratio", "N/A")))}</p>'
            f'<p>grade: PASS {escape(str(grade.get("PASS", 0)))} / '
            f'MARGINAL {escape(str(grade.get("MARGINAL", 0)))} / '
            f'FAIL {escape(str(grade.get("FAIL", 0)))}</p>'
            "</div>"
        )
    return f'<div class="summary">{"".join(cards)}</div>'


def _page_payloads(doc_dir: Path, page_no: int) -> dict[str, dict | None]:
    return {
        "hybrid": _load_json(doc_dir / f"p{page_no:03d}_hybrid.json"),
        "clova": _load_json(doc_dir / f"p{page_no:03d}_clova.json"),
        "true_hybrid": _load_json(doc_dir / f"p{page_no:03d}_true_hybrid.json"),
    }


def _render_page(doc_dir: Path, page_no: int, active: bool) -> str:
    payloads = _page_payloads(doc_dir, page_no)
    engines = "".join(_render_engine(payloads[engine], engine) for engine in ENGINES)
    active_class = " page-active" if active else ""
    return f'<section id="page-{page_no}" class="page{active_class}"><div class="engines">{engines}</div></section>'


def generate_html(doc_short: str, output_path: Path) -> Path:
    doc_dir = ROOT / "reports" / "ocr_compare" / doc_short
    if not doc_dir.exists():
        raise FileNotFoundError(f"결과 디렉터리를 찾을 수 없습니다: {doc_dir}")

    pages = _discover_pages(doc_dir)
    if not pages:
        raise ValueError(f"페이지 JSON을 찾을 수 없습니다: {doc_dir}")

    summary = _load_json(doc_dir / "summary.json")
    tabs = "".join(
        f'<button class="tab{" active" if index == 0 else ""}" data-page="{page}">p{page:03d}</button>'
        for index, page in enumerate(pages)
    )
    rendered_pages = "".join(_render_page(doc_dir, page, index == 0) for index, page in enumerate(pages))
    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OCR 비교 - {escape(doc_short)}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f9; color: #18202a; }}
    header {{ padding: 24px 28px 16px; background: #ffffff; border-bottom: 1px solid #d9dee7; position: sticky; top: 0; z-index: 5; }}
    h1 {{ font-size: 22px; margin: 0 0 14px; }}
    .summary {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }}
    .summary-card {{ background: #f9fafb; border: 1px solid #d9dee7; border-radius: 8px; padding: 12px; }}
    .summary-card h2 {{ font-size: 15px; margin: 0 0 8px; }}
    .summary-card p {{ margin: 4px 0; font-size: 13px; }}
    .tabs {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .tab {{ border: 1px solid #c8d0dc; background: #ffffff; border-radius: 6px; padding: 7px 10px; cursor: pointer; }}
    .tab.active {{ background: #1d4ed8; color: #ffffff; border-color: #1d4ed8; }}
    main {{ padding: 18px 20px 28px; }}
    .page {{ display: none; }}
    .page.page-active {{ display: block; }}
    .engines {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; align-items: start; }}
    .engine {{ background: #ffffff; border: 1px solid #d9dee7; border-radius: 8px; min-width: 0; overflow: hidden; }}
    .engine h3 {{ margin: 0; padding: 12px 14px; border-bottom: 1px solid #d9dee7; font-size: 16px; }}
    .engine-meta {{ display: flex; gap: 8px; flex-wrap: wrap; padding: 10px 14px; font-size: 12px; border-bottom: 1px solid #eef1f5; }}
    .block {{ margin: 12px; border: 1px solid #e0e5ec; border-radius: 8px; overflow: auto; }}
    .block-head {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 8px 10px; background: #f9fafb; border-bottom: 1px solid #e0e5ec; font-size: 12px; }}
    .bbox, .metric {{ color: #5d6776; }}
    .badge {{ border-radius: 999px; padding: 2px 7px; font-size: 12px; font-weight: 650; }}
    .native {{ background: #dbeafe; color: #1e40af; }}
    .geometric {{ background: #ffedd5; color: #9a3412; }}
    .grade-pass {{ background: #dcfce7; color: #166534; }}
    .grade-marginal {{ background: #fef9c3; color: #854d0e; }}
    .grade-fail {{ background: #fee2e2; color: #991b1b; }}
    .status {{ background: #eef2ff; color: #3730a3; }}
    pre {{ white-space: pre-wrap; word-break: keep-all; margin: 0; padding: 10px; font-size: 13px; line-height: 1.55; }}
    pre.error {{ background: #fff1f2; color: #9f1239; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #d6dce6; padding: 6px 7px; vertical-align: top; word-break: keep-all; }}
    th {{ background: #eef2f7; position: sticky; top: 0; }}
    .empty {{ padding: 10px; color: #697386; font-size: 13px; }}
    @media (max-width: 1200px) {{ .engines, .summary {{ grid-template-columns: 1fr; }} header {{ position: static; }} }}
  </style>
</head>
<body>
  <header>
    <h1>OCR 비교 - {escape(doc_short)}</h1>
    {_render_summary(summary)}
    <nav class="tabs">{tabs}</nav>
  </header>
  <main>{rendered_pages}</main>
  <script>
    const tabs = document.querySelectorAll(".tab");
    const pages = document.querySelectorAll(".page");
    tabs.forEach((tab) => {{
      tab.addEventListener("click", () => {{
        tabs.forEach((item) => item.classList.remove("active"));
        pages.forEach((item) => item.classList.remove("page-active"));
        tab.classList.add("active");
        document.getElementById(`page-${{tab.dataset.page}}`).classList.add("page-active");
      }});
    }});
  </script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate OCR comparison HTML")
    parser.add_argument("--doc", default="실무가이드")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "ocr_compare_v43_review.html")
    args = parser.parse_args(argv)

    output_path = generate_html(args.doc, args.output)
    print(f"[generate_ocr_html] wrote {output_path} ({output_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
