#!/usr/bin/env python3
"""Generate a self-contained OCR viewer with original page images."""

from __future__ import annotations

import argparse
import base64
from html import escape
import io
import json
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENGINES = [
    ("true_hybrid", "True Hybrid", "#0369a1"),
    ("clova", "CLOVA", "#059669"),
]


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _image_data_uri(path: Path, max_width: int = 1100) -> str:
    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            ratio = max_width / image.width
            image = image.resize((max_width, max(1, int(image.height * ratio))))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _discover_pages(doc_dir: Path) -> list[int]:
    pages: set[int] = set()
    for path in doc_dir.glob("p???_original.png"):
        pages.add(int(path.stem[1:4]))
    return sorted(pages)


def _page_payload(doc_dir: Path, page_no: int, engine: str) -> dict | None:
    return _load_json(doc_dir / f"p{page_no:03d}_{engine}.json")


def _table_count(payload: dict | None) -> int:
    if not payload:
        return 0
    metrics = payload.get("metrics") or {}
    return int(metrics.get("table_blocks") or sum(1 for block in payload.get("blocks", []) if block.get("block_type") == "table"))


def _raw_flags(payload: dict | None) -> tuple[bool, bool]:
    if not payload:
        return False, False
    vision = numeric = False
    for block in payload.get("blocks", []):
        raw = block.get("raw") or {}
        vision = vision or raw.get("vision_cleaned") is True
        numeric = numeric or raw.get("numeric_refined") is True
    return vision, numeric


def _quality_badge(block: dict) -> str:
    quality = block.get("quality") or {}
    grade = str(quality.get("grade") or "N/A")
    css = "pass" if grade == "PASS" else "fail" if grade == "FAIL" else "marginal"
    korean = int(round(float(quality.get("korean_ratio", 0.0)) * 100))
    chars = quality.get("chars", len(str(block.get("text") or "").replace(" ", "").replace("\n", "")))
    return f'<span class="badge-{css}">{escape(grade)}</span> <span class="muted">한글 {korean}% · {escape(str(chars))}자</span>'


def _source_badges(raw: dict, corrections_count: int, unresolved_count: int) -> str:
    badges = ['<span class="badge-blue">CLOVA 네이티브</span>' if raw.get("native_table") else '<span class="badge-purple">기하학적 재구성</span>']
    if raw.get("vision_cleaned") is True:
        badges.append('<span class="badge-violet">Vision 표 정제</span>')
    if raw.get("numeric_refined") is True:
        badges.append(f'<span class="badge-green">Vision 숫자 정제 {corrections_count}건</span>')
    if unresolved_count:
        badges.append(f'<span class="badge-gold">미해결 {unresolved_count}건</span>')
    return " ".join(badges)


def _render_table(block: dict) -> str:
    table_json = block.get("table_json") or {}
    headers = [str(header) for header in table_json.get("headers", [])]
    rows = table_json.get("rows", [])
    raw = block.get("raw") or {}
    corrected = {
        (int(item.get("row_index")), str(item.get("col")))
        for item in raw.get("numeric_corrections", [])
        if isinstance(item, dict) and "row_index" in item and item.get("col")
    }
    unresolved = {
        (int(item.get("row_index")), str(item.get("col")))
        for item in raw.get("numeric_unresolved_cells", [])
        if isinstance(item, dict) and "row_index" in item and item.get("col")
    }
    if not headers:
        return '<div class="no-data">table_json 없음</div>'

    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_rows: list[str] = []
    for row_index, row in enumerate(rows):
        cells: list[str] = []
        for header in headers:
            value = str(row.get(header, "") if isinstance(row, dict) else "")
            classes: list[str] = []
            if value == "":
                classes.append("empty-cell")
                display = "—"
            else:
                display = escape(value)
            if value == "[그림]":
                classes.append("fig-cell")
            if (row_index, header) in corrected:
                classes.append("refined-cell")
            if (row_index, header) in unresolved:
                classes.append("unresolved-cell")
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            cells.append(f"<td{class_attr}>{display}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div style="overflow-x:auto"><table class="t"><thead><tr>{head}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def _render_block(block: dict) -> str:
    if block.get("block_type") == "table":
        raw = block.get("raw") or {}
        corrections_count = len(raw.get("numeric_corrections") or [])
        unresolved_count = len(raw.get("numeric_unresolved_cells") or [])
        table_json = block.get("table_json") or {}
        return (
            '<div class="tbl-wrap"><div class="tbl-meta">'
            f"{_source_badges(raw, corrections_count, unresolved_count)} {_quality_badge(block)} "
            f'<span class="muted">{len(table_json.get("rows", []))}행 × {len(table_json.get("headers", []))}열</span>'
            f'</div>{_render_table(block)}</div>'
        )
    return f'<div class="txt-block">{_quality_badge(block)}<pre class="txt-pre">{escape(str(block.get("text") or ""))}</pre></div>'


def _render_engine(doc_dir: Path, page_no: int, engine: str, label: str, color: str) -> str:
    payload = _page_payload(doc_dir, page_no, engine)
    if payload is None:
        return f'<div class="eng-card"><div class="eng-title" style="color:{color}">{label}</div><div class="no-data">결과 JSON 없음</div></div>'
    metrics = payload.get("metrics") or {}
    blocks = payload.get("blocks", [])
    flags: list[str] = []
    for block in blocks:
        raw = block.get("raw") or {}
        if raw.get("vision_cleaned") is True:
            flags.append('<span class="badge-violet">Vision 표 정제</span>')
        if raw.get("numeric_refined") is True:
            flags.append(f'<span class="badge-green">Vision 숫자 정제 {len(raw.get("numeric_corrections") or [])}건</span>')
        if raw.get("numeric_unresolved_cells"):
            flags.append(f'<span class="badge-gold">미해결 {len(raw.get("numeric_unresolved_cells") or [])}건</span>')
    korean = int(round(float(metrics.get("avg_korean_ratio", 0.0)) * 100))
    rendered_blocks = "".join(_render_block(block) for block in blocks)
    return (
        '<div class="eng-card">'
        f'<div class="eng-title" style="color:{color}">{label}</div>'
        f'<div class="col-meta" style="border-color:{color}">'
        f'<span class="small-pill">표 {_table_count(payload)}블록</span>'
        f'<span class="muted">한글 {korean}%</span>'
        f'<span class="badge-pass">{escape(str(payload.get("status", "UNKNOWN")))}</span>'
        f'{" ".join(flags)}</div>{rendered_blocks}</div>'
    )


def generate_image_compare_html(doc_short: str, output_path: Path, pages: list[int] | None = None) -> Path:
    doc_dir = ROOT / "reports" / "ocr_compare" / doc_short
    if not doc_dir.exists():
        raise FileNotFoundError(f"결과 디렉터리를 찾을 수 없습니다: {doc_dir}")
    selected_pages = pages or _discover_pages(doc_dir)
    if not selected_pages:
        raise ValueError(f"원본 페이지 이미지를 찾을 수 없습니다: {doc_dir}")

    nav: list[str] = []
    page_sections: list[str] = []
    for index, page_no in enumerate(selected_pages):
        true_payload = _page_payload(doc_dir, page_no, "true_hybrid")
        vision, numeric = _raw_flags(true_payload)
        flag_text = (" V" if vision else "") + (" N" if numeric else "")
        nav.append(
            f'<button class="nb{" on" if index == 0 else ""}" onclick="show({page_no})" id="b{page_no}">'
            f'p{page_no:03d} 표{_table_count(true_payload)}{flag_text}</button>'
        )
        badges = [f'<span class="page-badge">표 {_table_count(true_payload)}개</span>']
        if vision:
            badges.append('<span class="page-badge vision">Vision 표 정제</span>')
        if numeric:
            badges.append('<span class="page-badge numeric">Vision 숫자 정제</span>')
        image_path = doc_dir / f"p{page_no:03d}_original.png"
        image_src = _image_data_uri(image_path) if image_path.exists() else ""
        engines = "".join(_render_engine(doc_dir, page_no, *engine) for engine in ENGINES)
        page_sections.append(
            f'<div class="pg{" on" if index == 0 else ""}" id="p{page_no}">'
            f'<div class="pg-title">페이지 {page_no:03d} {" ".join(badges)}</div>'
            f'<div class="main-grid"><div class="img-panel"><h3>원본 페이지</h3>'
            f'<img src="{image_src}" onclick="zoom(this)" alt="p{page_no:03d}"></div>'
            f'<div class="ocr-side">{engines}</div></div></div>'
        )

    html = HTML_TEMPLATE.replace("__NAV__", "".join(nav)).replace("__PAGES__", "".join(page_sections))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OCR 원본 대조 뷰어 v47</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Apple SD Gothic Neo","Noto Sans KR",sans-serif;background:#f1f5f9;color:#111;font-size:13px}
.hdr{background:#1e3a5f;color:#fff;padding:16px 24px}
.hdr h1{font-size:18px;margin-bottom:3px}
.hdr p{font-size:11px;opacity:.75}
.note{background:#fffbeb;border-left:4px solid #f59e0b;padding:9px 16px;margin:10px 18px;font-size:12px;color:#78350f;border-radius:0 4px 4px 0;line-height:1.7}
.nav{display:flex;gap:5px;padding:10px 18px;flex-wrap:wrap;background:#fff;border-bottom:1px solid #e5e7eb;position:sticky;top:0;z-index:5}
.nb{padding:4px 11px;border-radius:5px;border:1px solid #d1d5db;background:#fff;cursor:pointer;font-size:12px;color:#374151}
.nb:hover,.nb.on{background:#1e3a5f;color:#fff;border-color:#1e3a5f}
.pg{display:none;padding:14px 18px 40px}.pg.on{display:block}
.pg-title{font-size:15px;font-weight:bold;color:#1e3a5f;margin-bottom:12px;padding-bottom:7px;border-bottom:2px solid #1e3a5f;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.main-grid{display:grid;grid-template-columns:420px 1fr;gap:12px;align-items:start}
@media(max-width:1100px){.main-grid{grid-template-columns:1fr}}
.img-panel{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);padding:12px;position:sticky;top:52px}
.img-panel h3{font-size:12px;color:#374151;margin-bottom:6px}
.img-panel img{width:100%;height:auto;border:1px solid #e5e7eb;border-radius:3px;cursor:zoom-in}
.ocr-side{display:flex;flex-direction:column;gap:10px}
.eng-card{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);padding:12px}
.eng-title{font-size:12px;font-weight:bold;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #e5e7eb}
.col-meta{border-left:3px solid #ccc;padding-left:8px;margin-bottom:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.tbl-wrap{margin:6px 0}.tbl-meta{margin-bottom:4px;display:flex;gap:5px;align-items:center;flex-wrap:wrap}
.t{border-collapse:collapse;font-size:11px;width:100%}
.t th{background:#1e3a5f;color:#fff;padding:3px 6px;text-align:left;font-weight:normal;white-space:nowrap}
.t td{border:1px solid #d1d5db;padding:2px 5px;vertical-align:top;word-break:break-all;font-size:11px}
.t tr:nth-child(even) td{background:#f9fafb}
.fig-cell{background:#fef3c7!important;color:#92400e;font-weight:bold;text-align:center}
.refined-cell{background:#dcfce7!important;color:#14532d!important;font-weight:bold;text-align:center;box-shadow:inset 0 0 0 2px #22c55e}
.unresolved-cell{background:#fef3c7!important;color:#92400e!important;font-weight:bold;text-align:center;box-shadow:inset 0 0 0 2px #f59e0b}
.empty-cell{color:#d1d5db;text-align:center;font-size:10px}
.txt-block{margin:5px 0}.txt-pre{font-size:11px;white-space:pre-wrap;background:#f9fafb;padding:5px 7px;border-radius:3px;max-height:140px;overflow-y:auto;margin-top:3px;line-height:1.5}
.badge-blue{background:#0369a1;color:#fff;padding:1px 6px;border-radius:3px;font-size:10px}
.badge-purple,.badge-violet{background:#7c3aed;color:#fff;padding:1px 6px;border-radius:3px;font-size:10px}
.badge-green{background:#16a34a;color:#fff;padding:1px 6px;border-radius:3px;font-size:10px}
.badge-gold{background:#f59e0b;color:#fff;padding:1px 6px;border-radius:3px;font-size:10px}
.badge-pass{background:#22c55e;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px}
.badge-marginal{background:#fef3c7;color:#92400e;padding:1px 5px;border-radius:3px;font-size:10px}
.badge-fail{background:#fee2e2;color:#991b1b;padding:1px 5px;border-radius:3px;font-size:10px}
.small-pill,.page-badge{background:#e5e7eb;padding:1px 6px;border-radius:3px;font-size:10px}
.page-badge{background:#dbeafe;color:#1d4ed8;padding:2px 7px;font-size:11px}.page-badge.vision{background:#ede9fe;color:#5b21b6}.page-badge.numeric{background:#dcfce7;color:#166534}
.no-data,.muted{color:#9ca3af;font-size:11px}
#lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:9999;align-items:center;justify-content:center}
#lb.on{display:flex}#lb img{max-width:92vw;max-height:92vh;border-radius:4px;box-shadow:0 8px 32px rgba(0,0,0,.5)}
#lbc{position:fixed;top:14px;right:22px;color:#fff;font-size:30px;cursor:pointer;line-height:1;font-weight:300}
</style>
</head>
<body>
<div class="hdr"><h1>OCR 결과 원본 대조 뷰어 v47</h1><p>실무가이드 · 원본 페이지 대조 · Vision 숫자 셀 정제 보정/미해결 표시</p></div>
<div class="note"><strong>v47</strong>: 수술종수 3개 컬럼 그룹이 부분 누락된 행도 Vision LLM 판독 대상으로 포함합니다. 초록색은 적용된 Vision 숫자 보정, 노란색은 미해결 셀입니다.</div>
<div class="nav">__NAV__</div>
__PAGES__
<div id="lb" onclick="this.classList.remove('on')"><span id="lbc">×</span><img id="lbi" src="" alt="zoom"></div>
<script>
function show(p){document.querySelectorAll('.pg').forEach(x=>x.classList.remove('on'));document.querySelectorAll('.nb').forEach(x=>x.classList.remove('on'));document.getElementById('p'+p).classList.add('on');document.getElementById('b'+p).classList.add('on')}
function zoom(img){document.getElementById('lbi').src=img.src;document.getElementById('lb').classList.add('on')}
</script>
</body>
</html>
"""


def _parse_pages(value: str | None) -> list[int] | None:
    if not value:
        return None
    pages: list[int] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start, end = token.split("-", 1)
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(token))
    return sorted(set(pages))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate OCR original-image comparison HTML")
    parser.add_argument("--doc", default="실무가이드")
    parser.add_argument("--pages", default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "ocr_compare_v47_image_compare.html")
    args = parser.parse_args()

    output_path = generate_image_compare_html(args.doc, args.output, _parse_pages(args.pages))
    print(f"[generate_ocr_image_compare_html] wrote {output_path} ({output_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
