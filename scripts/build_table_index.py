"""Build deterministic Parquet indexes for surgery grades and disability rates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TABLE_DIR = ROOT / "data" / "extracted" / "실무가이드" / "tables"
INDEX_DIR = ROOT / "data" / "index"
SURGERY_OUT = INDEX_DIR / "surgery_grades.parquet"
DISABILITY_OUT = INDEX_DIR / "disability_rates.parquet"

DISABILITY_BODY_PART_MAP = {
    "p235_t00.json": "눈의 장해",
    "p241_t00.json": "귀의 장해",
    "p244_t00.json": "코의 장해",
    "p246_t00.json": "씹어먹거나 말하는 장해",
    "p248_t00.json": "외모의 추상 장해",
    "p250_t00.json": "척추(등뼈)의 장해",
    "p253_t00.json": "체간골의 장해",
    "p254_t00.json": "팔의 장해",
    "p256_t00.json": "다리의 장해",
    "p263_t00.json": "손가락의 장해",
    "p265_t00.json": "발가락의 장해",
    "p266_t00.json": "흉복부장기 및 비뇨생식기의 장해",
    "p267_t00.json": "신경계·정신행동 장해",
    "p270_t00.json": "신경계·정신행동 장해 (ADL)",
    "p276_t00.json": None,
    "p278_t00.json": "정신행동 장해 (GAF)",
}


def _normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").strip()
    return re.sub(r"\s+", " ", text)


def _page_label(path: Path) -> int:
    match = re.match(r"p(\d+)_", path.name)
    if not match:
        raise ValueError(f"Cannot infer page label from {path.name}")
    return int(match.group(1)) + 1


def _load_table(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        loaded = json.load(file)
    return loaded if isinstance(loaded, dict) else {}


def normalize_surgery_headers(headers: list[str]) -> tuple[list[str], list[str], str | None, str | None, str | None]:
    col_13 = next((h for h in headers if "1-3종" in h or h == "col_3"), None)
    col_15 = next((h for h in headers if "1-5종" in h and not h.startswith(("신", "산"))), None)
    col_s15 = next((h for h in headers if "신1-5종" in h or "산1-5종" in h), None)
    name_cols = [h for h in headers if h.startswith("수술명")]
    desc_cols = [h for h in headers if h.startswith("수술해설")]
    return name_cols, desc_cols, col_13, col_15, col_s15


def _normalize_grade(value: Any) -> str:
    text = _normalize_text(value)
    return "" if text == "[그림]" else text


def expand_surgery_row(
    row: dict,
    name_cols: list[str],
    desc_cols: list[str],
    col_13: str | None,
    col_15: str | None,
    col_s15: str | None,
) -> list[dict]:
    desc_parts: list[str] = []
    seen_desc: set[str] = set()
    for col in desc_cols:
        desc = _normalize_text(row.get(col, "")).replace("[그림]", "").strip()
        if desc and desc not in seen_desc:
            seen_desc.add(desc)
            desc_parts.append(desc)
    desc_text = " ".join(desc_parts)

    grade_vals = {
        "종_1_3": _normalize_grade(row.get(col_13, "")) if col_13 else "",
        "종_1_5": _normalize_grade(row.get(col_15, "")) if col_15 else "",
        "종_신1_5": _normalize_grade(row.get(col_s15, "")) if col_s15 else "",
    }

    rows_out: list[dict] = []
    seen_names: set[str] = set()
    for col in name_cols:
        raw_name = str(row.get(col, "") or "").strip()
        normalized_name = _normalize_text(raw_name)
        if not normalized_name or normalized_name == "[그림]" or normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        rows_out.append(
            {
                "수술명": normalized_name,
                "수술명_원문": raw_name,
                "수술해설": desc_text,
                **grade_vals,
            }
        )
    return rows_out


def _is_surgery_table(headers: list[str]) -> bool:
    return any("1-3종" in h or h == "col_3" or "1-5종" in h for h in headers)


def build_surgery_rows(stats: dict[str, int]) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(TABLE_DIR.glob("p*_t*.json")):
        table = _load_table(path)
        headers = [str(header) for header in table.get("headers", [])]
        table_rows = table.get("rows", [])
        if not _is_surgery_table(headers) or not isinstance(table_rows, list):
            continue

        name_cols, desc_cols, col_13, col_15, col_s15 = normalize_surgery_headers(headers)
        for row in table_rows:
            if not isinstance(row, dict):
                continue
            expanded = expand_surgery_row(row, name_cols, desc_cols, col_13, col_15, col_s15)
            if not expanded:
                stats["skipped_empty_surgery_name"] += 1
                continue
            for item in expanded:
                item.update(
                    {
                        "source_page_label": _page_label(path),
                        "source_file": path.name,
                        "table_type": "surgery_grade",
                        "table_group_id": "수술종수표",
                        "group_page_range": "33-175",
                    }
                )
                rows.append(item)

    first_page = min((row["source_page_label"] for row in rows), default=None)
    for row in rows:
        row["is_page_continued"] = bool(first_page is not None and row["source_page_label"] > first_page)
    return rows


def parse_rate(raw: Any) -> list[dict]:
    text = str(raw or "").strip()
    if not text or text == "[그림]":
        return []

    results: list[dict] = []
    for part in [part.strip() for part in text.replace("%", "").split("\n") if part.strip()]:
        if "~" in part:
            nums = re.findall(r"\d+(?:\.\d+)?", part)
            if len(nums) >= 2:
                results.append(
                    {
                        "지급률": None,
                        "지급률_원문": text,
                        "지급률_범위_최소": float(nums[0]),
                        "지급률_범위_최대": float(nums[1]),
                    }
                )
        else:
            nums = re.findall(r"\d+(?:\.\d+)?", part)
            if nums:
                results.append(
                    {
                        "지급률": nums[0].rstrip("0").rstrip(".") if "." in nums[0] else nums[0],
                        "지급률_원문": text,
                        "지급률_범위_최소": None,
                        "지급률_범위_최대": None,
                    }
                )
    return results


def expand_disability_row(row: dict, classification_col: str, rate_col: str) -> list[dict]:
    classification_raw = str(row.get(classification_col, "") or "").strip()
    rate_raw = str(row.get(rate_col, "") or "").strip()
    class_parts = [part.strip() for part in classification_raw.split("\n") if part.strip()]
    rate_results = parse_rate(rate_raw)

    if not class_parts or not rate_results:
        combined = _normalize_text(" ".join(class_parts)) if class_parts else ""
        return [{"장해분류": combined, "장해분류_원문": classification_raw, **rate} for rate in rate_results]

    if len(class_parts) == len(rate_results):
        return [
            {"장해분류": _normalize_text(classification), "장해분류_원문": classification, **rate}
            for classification, rate in zip(class_parts, rate_results)
        ]

    combined = _normalize_text(" / ".join(class_parts))
    return [{"장해분류": combined, "장해분류_원문": classification_raw, **rate} for rate in rate_results]


def _build_adl_rows(path: Path, rows: list[dict], body_part: str) -> list[dict]:
    output: list[dict] = []
    for row in rows:
        category = _normalize_text(row.get("유 형", ""))
        rate_text = str(row.get("제한정도에 따른 지급률", "") or "").strip()
        if not category or not rate_text:
            continue
        output.append(
            {
                "신체부위": body_part,
                "장해분류": category,
                "장해분류_원문": str(row.get("유 형", "") or "").strip(),
                "지급률": None,
                "지급률_원문": rate_text,
                "지급률_범위_최소": None,
                "지급률_범위_최대": None,
                "source_page_label": _page_label(path),
                "source_file": path.name,
                "table_type": "disability_rate",
                "table_group_id": body_part,
            }
        )
    return output


def _build_gaf_rows(path: Path, rows: list[dict], body_part: str) -> list[dict]:
    output: list[dict] = []
    for row in rows:
        category = _normalize_text(f"{row.get('GAF 점수', '')} {row.get('판 단 기 준', '')}")
        if not category:
            continue
        for rate in parse_rate(row.get("장해율", "")):
            output.append(
                {
                    "신체부위": body_part,
                    "장해분류": category,
                    "장해분류_원문": category,
                    **rate,
                    "source_page_label": _page_label(path),
                    "source_file": path.name,
                    "table_type": "disability_rate",
                    "table_group_id": body_part,
                }
            )
    return output


def build_disability_rows(stats: dict[str, int]) -> list[dict]:
    rows_out: list[dict] = []
    for path in sorted(TABLE_DIR.glob("p*_t*.json")):
        body_part = DISABILITY_BODY_PART_MAP.get(path.name)
        table = _load_table(path)
        headers = [str(header) for header in table.get("headers", [])]
        table_rows = table.get("rows", [])
        if body_part is None:
            if path.name in DISABILITY_BODY_PART_MAP:
                stats["skipped_disability_files"] += 1
            continue
        if not isinstance(table_rows, list):
            continue

        if path.name == "p270_t00.json":
            rows_out.extend(_build_adl_rows(path, table_rows, body_part))
            continue
        if path.name == "p278_t00.json":
            rows_out.extend(_build_gaf_rows(path, table_rows, body_part))
            continue

        if "장해의 분류" in headers and "지급률" in headers:
            classification_col = "장해의 분류"
            rate_col = "지급률"
        elif len(headers) >= 2:
            classification_col = headers[0]
            rate_col = headers[1]
        else:
            continue

        for row in table_rows:
            if not isinstance(row, dict):
                continue
            if str(row.get(classification_col, "") or "").strip() == "[그림]":
                stats["skipped_figure_disability"] += 1
                continue
            expanded = expand_disability_row(row, classification_col, rate_col)
            if not expanded:
                stats["skipped_empty_disability_rate"] += 1
                continue
            for item in expanded:
                if not item.get("장해분류"):
                    stats["skipped_empty_disability_classification"] += 1
                    continue
                item.update(
                    {
                        "신체부위": body_part,
                        "source_page_label": _page_label(path),
                        "source_file": path.name,
                        "table_type": "disability_rate",
                        "table_group_id": body_part,
                    }
                )
                rows_out.append(item)

    first_page_by_group: dict[str, int] = {}
    for row in rows_out:
        group = row["table_group_id"]
        first_page_by_group[group] = min(first_page_by_group.get(group, row["source_page_label"]), row["source_page_label"])
    for row in rows_out:
        row["is_page_continued"] = row["source_page_label"] > first_page_by_group[row["table_group_id"]]
    return rows_out


def main() -> None:
    stats = {
        "skipped_empty_surgery_name": 0,
        "skipped_figure_disability": 0,
        "skipped_empty_disability_rate": 0,
        "skipped_empty_disability_classification": 0,
        "skipped_disability_files": 0,
    }
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    surgery_rows = build_surgery_rows(stats)
    disability_rows = build_disability_rows(stats)

    pd.DataFrame(surgery_rows).to_parquet(SURGERY_OUT, index=False)
    pd.DataFrame(disability_rows).to_parquet(DISABILITY_OUT, index=False)

    print(f"surgery_grades: {len(surgery_rows)} rows -> {SURGERY_OUT}")
    print(f"disability_rates: {len(disability_rows)} rows -> {DISABILITY_OUT}")
    print("skip_stats:")
    for key, value in stats.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
