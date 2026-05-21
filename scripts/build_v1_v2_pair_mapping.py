#!/usr/bin/env python3
"""v2 canonical 기준으로 v1-v2 1:1 매핑 파일을 생성한다."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_V1 = ROOT / "data" / "processed" / "chunks_v1_rechunked_target16.jsonl"
DEFAULT_V2 = ROOT / "data" / "processed" / "chunks_v2_manual.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "mapping"
DEFAULT_LOW_CONF_DIR = ROOT / "reports" / "mapping_low_confidence"


def _normalize_text(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip().lower()
    compact = re.sub(r"[^\w가-힣%./()\- ]+", "", compact)
    return compact


@dataclass
class ChunkRow:
    chunk_id: str
    doc_short: str
    page_start: int
    content_type: str
    text: str
    local_order: int


def _load_doc_chunks(path: Path, doc_short: str) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            meta = row.get("metadata", {})
            if meta.get("doc_short") != doc_short:
                continue
            rows.append(row)
    return rows


def _with_local_order(rows: list[dict]) -> list[ChunkRow]:
    grouped: dict[tuple[int, str], int] = {}
    parsed: list[ChunkRow] = []
    for row in rows:
        meta = row.get("metadata", {})
        page = int(meta.get("page_start") or 0)
        ctype = str(meta.get("content_type") or "text")
        key = (page, ctype)
        order = grouped.get(key, 0)
        grouped[key] = order + 1
        parsed.append(
            ChunkRow(
                chunk_id=row["id"],
                doc_short=str(meta.get("doc_short") or ""),
                page_start=page,
                content_type=ctype,
                text=str(row.get("text") or ""),
                local_order=order,
            )
        )
    return parsed


def _score(a: str, b: str) -> float:
    na = _normalize_text(a)
    nb = _normalize_text(b)
    if not na and not nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _match_page_type(
    v1_rows: list[ChunkRow],
    v2_rows: list[ChunkRow],
    threshold: float,
) -> list[dict]:
    pairs: list[dict] = []
    v1_by_order = {row.local_order: row for row in v1_rows}
    used_v1: set[str] = set()

    # 1) exact by local order
    for v2 in v2_rows:
        v1 = v1_by_order.get(v2.local_order)
        if v1 is None:
            continue
        s = _score(v1.text, v2.text)
        pairs.append(
            {
                "canonical_chunk_id": v2.chunk_id,
                "v1_chunk_id": v1.chunk_id,
                "doc_short": v2.doc_short,
                "page_start": v2.page_start,
                "content_type": v2.content_type,
                "match_type": "exact_order",
                "score": round(s, 6),
                "confidence": "high" if s >= threshold else "low",
                "use_v1": s >= threshold,
            }
        )
        used_v1.add(v1.chunk_id)

    # 2) fallback fuzzy for unmatched v2
    unmatched_v2 = {row.chunk_id: row for row in v2_rows if row.chunk_id not in {p["canonical_chunk_id"] for p in pairs}}
    remaining_v1 = [row for row in v1_rows if row.chunk_id not in used_v1]
    for v2 in unmatched_v2.values():
        best = None
        for v1 in remaining_v1:
            s = _score(v1.text, v2.text)
            if best is None or s > best[0]:
                best = (s, v1)
        if best is None:
            pairs.append(
                {
                    "canonical_chunk_id": v2.chunk_id,
                    "v1_chunk_id": None,
                    "doc_short": v2.doc_short,
                    "page_start": v2.page_start,
                    "content_type": v2.content_type,
                    "match_type": "unmatched",
                    "score": 0.0,
                    "confidence": "low",
                    "use_v1": False,
                }
            )
            continue
        s, v1 = best
        remaining_v1 = [row for row in remaining_v1 if row.chunk_id != v1.chunk_id]
        pairs.append(
            {
                "canonical_chunk_id": v2.chunk_id,
                "v1_chunk_id": v1.chunk_id if s >= threshold else None,
                "doc_short": v2.doc_short,
                "page_start": v2.page_start,
                "content_type": v2.content_type,
                "match_type": "fuzzy",
                "score": round(s, 6),
                "confidence": "high" if s >= threshold else "low",
                "use_v1": s >= threshold,
            }
        )
    return pairs


def build_doc_mapping(v1_chunks: list[ChunkRow], v2_chunks: list[ChunkRow], threshold: float) -> list[dict]:
    pages_types = sorted({(r.page_start, r.content_type) for r in v2_chunks})
    out: list[dict] = []
    for page, ctype in pages_types:
        v2_rows = [row for row in v2_chunks if row.page_start == page and row.content_type == ctype]
        v1_rows = [row for row in v1_chunks if row.page_start == page and row.content_type == ctype]
        out.extend(_match_page_type(v1_rows, v2_rows, threshold))
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_chunk_lookup(path: Path, docs: list[str]) -> dict[str, dict]:
    allowed = set(docs)
    lookup: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            meta = row.get("metadata", {})
            if meta.get("doc_short") not in allowed:
                continue
            lookup[row["id"]] = row
    return lookup


def _emit_low_confidence_report(
    *,
    docs: list[str],
    out_dir: Path,
    mapping_dir: Path,
    v1_lookup: dict[str, dict],
    v2_lookup: dict[str, dict],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []

    for doc in docs:
        mapping_path = mapping_dir / f"v1_v2_pairs_{doc}.jsonl"
        rows: list[dict] = []
        total = low = 0
        with mapping_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                total += 1
                pair = json.loads(line)
                if pair.get("confidence") != "low":
                    continue
                low += 1
                canonical_id = pair.get("canonical_chunk_id")
                v1_id = pair.get("v1_chunk_id")
                v2_row = v2_lookup.get(canonical_id, {})
                v1_row = v1_lookup.get(v1_id, {}) if v1_id else {}
                rows.append(
                    {
                        "doc_short": doc,
                        "canonical_chunk_id": canonical_id,
                        "v1_chunk_id": v1_id,
                        "page_start": pair.get("page_start"),
                        "content_type": pair.get("content_type"),
                        "match_type": pair.get("match_type"),
                        "score": pair.get("score"),
                        "use_v1": pair.get("use_v1"),
                        "v2_text_preview": str(v2_row.get("text", ""))[:300],
                        "v1_text_preview": str(v1_row.get("text", ""))[:300] if v1_row else "",
                    }
                )
        report_path = out_dir / f"low_confidence_{doc}.jsonl"
        _write_jsonl(report_path, rows)
        summary.append(
            {
                "doc_short": doc,
                "total_pairs": total,
                "low_confidence_pairs": low,
                "ratio_low_confidence": round((low / total), 6) if total else 0.0,
                "report_path": str(report_path),
            }
        )
        print(f"[low-conf] {doc}: total={total:,} low={low:,} report={report_path}")

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[low-conf] summary: {summary_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build v1-v2 OCR pair mappings")
    parser.add_argument("--v1-chunks", type=Path, default=DEFAULT_V1)
    parser.add_argument("--v2-chunks", type=Path, default=DEFAULT_V2)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--low-conf-dir", type=Path, default=DEFAULT_LOW_CONF_DIR)
    parser.add_argument("--threshold", type=float, default=0.95)
    parser.add_argument("--docs", nargs="*", default=["실무가이드", "상담사례집"])
    parser.add_argument(
        "--emit-low-confidence-report",
        action="store_true",
        help="low-confidence 매핑 검수 리포트를 자동 생성한다.",
    )
    args = parser.parse_args()

    v1_path = args.v1_chunks if args.v1_chunks.is_absolute() else ROOT / args.v1_chunks
    v2_path = args.v2_chunks if args.v2_chunks.is_absolute() else ROOT / args.v2_chunks
    out_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    low_conf_dir = args.low_conf_dir if args.low_conf_dir.is_absolute() else ROOT / args.low_conf_dir

    for doc in args.docs:
        v1_rows = _with_local_order(_load_doc_chunks(v1_path, doc))
        v2_rows = _with_local_order(_load_doc_chunks(v2_path, doc))
        pairs = build_doc_mapping(v1_rows, v2_rows, args.threshold)
        out_path = out_dir / f"v1_v2_pairs_{doc}.jsonl"
        _write_jsonl(out_path, pairs)

        high = sum(1 for row in pairs if row["confidence"] == "high")
        low = sum(1 for row in pairs if row["confidence"] == "low")
        linked = sum(1 for row in pairs if row["v1_chunk_id"])
        print(f"[mapping] {doc}: canonical(v2)={len(v2_rows):,} pairs={len(pairs):,} linked={linked:,} high={high:,} low={low:,}")
        print(f"[mapping] output: {out_path}")

    if args.emit_low_confidence_report:
        v1_lookup = _build_chunk_lookup(v1_path, args.docs)
        v2_lookup = _build_chunk_lookup(v2_path, args.docs)
        _emit_low_confidence_report(
            docs=args.docs,
            out_dir=low_conf_dir,
            mapping_dir=out_dir,
            v1_lookup=v1_lookup,
            v2_lookup=v2_lookup,
        )


if __name__ == "__main__":
    main()
