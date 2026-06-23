#!/usr/bin/env python3
"""Review and update approved claim calculation rule manifests."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.claim_calculation.rule_registry import ClaimRuleRegistry

DEFAULT_RULES_PATH = PROJECT_ROOT / "data/rules/claim_deductible_rules.active.json"
SECTIONS = ("rules", "prescription_rules", "special_rules")
COMMON_FIELDS = ("description", "source_page", "source_clause", "source_chunk_id", "source_status")
EDITABLE_FIELDS = {
    "rules": COMMON_FIELDS
    + (
        "copay_ratio",
        "min_deductible",
        "min_deductible_by_facility",
        "per_visit_limit",
        "annual_limit",
        "annual_visit_limit",
    ),
    "prescription_rules": COMMON_FIELDS + ("deductible_amount", "per_visit_limit"),
    "special_rules": COMMON_FIELDS + ("payout_ratio", "daily_limit"),
}
NULLABLE_FIELDS = {"per_visit_limit", "annual_limit", "annual_visit_limit", "payout_ratio", "daily_limit", "source_status"}
INTEGER_FIELDS = {"annual_visit_limit"}
JSON_FIELDS = {"min_deductible_by_facility"}
FIELD_LABELS = {
    "description": "실무 설명",
    "source_page": "근거 페이지",
    "source_clause": "근거 조항",
    "source_chunk_id": "근거 chunk_id",
    "source_status": "근거 상태",
    "copay_ratio": "공제율",
    "min_deductible": "최소 공제금",
    "min_deductible_by_facility": "기관별 최소 공제금",
    "per_visit_limit": "회당 한도",
    "annual_limit": "연간 한도",
    "annual_visit_limit": "연간 횟수 한도",
    "deductible_amount": "처방 공제금",
    "payout_ratio": "특례 지급률",
    "daily_limit": "일 한도",
}


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def active_rows(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for section in SECTIONS:
        for row in payload.get(section) or []:
            if row.get("approval_status") == "active":
                rows.append((section, row))
    return rows


def find_rule(payload: dict[str, Any], rule_id: str) -> tuple[str, dict[str, Any]]:
    for section, row in active_rows(payload):
        if row.get("rule_id") == rule_id:
            return section, row
    raise KeyError(f"active rule not found: {rule_id}")


def parse_value(field: str, raw_value: str) -> Any:
    value = raw_value.strip()
    if value.lower() in {"", "null", "none"}:
        if field in NULLABLE_FIELDS:
            return None if field != "source_status" else ""
        raise ValueError(f"{field} cannot be empty")
    if field in JSON_FIELDS:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError(f"{field} must be a JSON object")
        return parsed
    if field in INTEGER_FIELDS:
        return int(value)
    return value


def validate_payload(payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
        tmp_path = Path(fp.name)
    try:
        ClaimRuleRegistry.from_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def json_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return "null"
    return str(value)


def rule_summary(section: str, row: dict[str, Any]) -> str:
    if section == "rules":
        return f"{row.get('generation', '')} {row.get('category', '')} {row.get('visit_type', '')} {row.get('facility_grade', '')}".strip()
    if section == "prescription_rules":
        return f"{row.get('generation', '')} 처방조제".strip()
    return str(row.get("special_type") or "특례")


def format_rule_detail(section: str, row: dict[str, Any]) -> str:
    lines = [
        f"룰 ID: {row.get('rule_id')}",
        f"구분: {rule_summary(section, row)}",
        f"설명: {row.get('description', '')}",
        "",
        "현재 값:",
    ]
    for field in EDITABLE_FIELDS[section]:
        lines.append(f"- {FIELD_LABELS.get(field, field)} ({field}): {json_text(row.get(field))}")
    lines.extend(
        [
            "",
            "근거:",
            f"- 문서: {row.get('source_doc', '')}",
            f"- 페이지: {row.get('source_page', '')}",
            f"- 조항: {row.get('source_clause', '')}",
            f"- chunk_id: {row.get('source_chunk_id', '')}",
            "",
            "값을 수정할 때는 원문 근거 또는 실무자 검토 사유를 반드시 남겨 주세요.",
        ]
    )
    return "\n".join(lines)


def write_manifest(path: Path, payload: dict[str, Any], event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = event["reviewed_at"].replace(":", "").replace("+", "Z")
    backup_path = backup_dir / f"{path.stem}.{timestamp}{path.suffix}"
    if path.exists():
        shutil.copy2(path, backup_path)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    event["backup_path"] = str(backup_path)
    log_path = path.parent / "claim_rule_review_log.jsonl"
    with log_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def update_rule_value(
    path: Path,
    rule_id: str,
    field: str,
    raw_value: str,
    reviewer: str,
    note: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    reviewer = reviewer.strip()
    note = note.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    if not note:
        raise ValueError("review note is required")
    payload = load_manifest(path)
    updated = copy.deepcopy(payload)
    section, row = find_rule(updated, rule_id)
    if field not in EDITABLE_FIELDS[section]:
        raise ValueError(f"{field} is not editable for {section}")
    old_value = row.get(field)
    new_value = parse_value(field, raw_value)
    row[field] = new_value
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row["last_reviewed_at"] = now
    row["last_reviewed_by"] = reviewer
    row["last_review_note"] = note
    validate_payload(updated)
    event = {
        "event": "active_rule_update",
        "reviewed_at": now,
        "reviewer": reviewer,
        "rule_id": rule_id,
        "section": section,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "note": note,
        "dry_run": dry_run,
    }
    if not dry_run:
        write_manifest(path, updated, event)
    return event


def list_json(path: Path) -> None:
    payload = load_manifest(path)
    rows = [
        {
            "rule_id": row.get("rule_id"),
            "section": section,
            "summary": rule_summary(section, row),
            "description": row.get("description", ""),
        }
        for section, row in active_rows(payload)
    ]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def show_rule(path: Path, rule_id: str) -> None:
    payload = load_manifest(path)
    section, row = find_rule(payload, rule_id)
    print(format_rule_detail(section, row))


def print_editable_fields(path: Path, rule_id: str) -> None:
    payload = load_manifest(path)
    section, row = find_rule(payload, rule_id)
    rows = [
        {"field": field, "label": FIELD_LABELS.get(field, field), "current_value": row.get(field)}
        for field in EDITABLE_FIELDS[section]
    ]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def zenity(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["zenity", *args], text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "zenity cancelled")
    return result


def require_gui(dry_run: bool) -> None:
    if dry_run:
        return
    if not (sys.platform.startswith("linux") and ("DISPLAY" in __import__("os").environ or "WAYLAND_DISPLAY" in __import__("os").environ)):
        raise RuntimeError("DISPLAY/WAYLAND_DISPLAY is not set. Run this from the DGX desktop session.")
    if shutil.which("zenity") is None:
        raise RuntimeError("zenity is required for active rule review GUI")


def list_height(row_count: int) -> int:
    return max(340, min(720, 190 + row_count * 34))


def run_gui(path: Path, dry_run: bool) -> None:
    require_gui(dry_run)
    payload = load_manifest(path)
    rows = active_rows(payload)
    if dry_run:
        print(f"active_rule_count={len(rows)}")
        if rows:
            print(format_rule_detail(rows[0][0], rows[0][1]))
        return
    while True:
        list_args = [
            "--list",
            "--title=액티브 룰 검토",
            "--text=수정할 승인 완료 룰을 선택하세요. 값 수정은 저장 전 전체 manifest 검증을 통과해야 합니다.",
            "--width=900",
            f"--height={list_height(len(rows))}",
            "--column=rule_id",
            "--column=구분",
            "--column=설명",
            "--print-column=1",
        ]
        for section, row in rows:
            list_args.extend([str(row.get("rule_id")), rule_summary(section, row), str(row.get("description", ""))])
        selected = zenity(*list_args, check=False)
        if selected.returncode != 0 or not selected.stdout.strip():
            return
        rule_id = selected.stdout.strip()
        section, row = find_rule(load_manifest(path), rule_id)
        detail = format_rule_detail(section, row)
        field_args = [
            "--list",
            "--title=수정 항목 선택",
            f"--text={detail}",
            "--width=920",
            "--height=680",
            "--column=field",
            "--column=표시명",
            "--column=현재값",
            "--hide-column=1",
            "--print-column=1",
        ]
        for field in EDITABLE_FIELDS[section]:
            field_args.extend([field, FIELD_LABELS.get(field, field), json_text(row.get(field))])
        picked = zenity(*field_args, check=False)
        if picked.returncode != 0 or not picked.stdout.strip():
            continue
        field = picked.stdout.strip()
        new_value = zenity(
            "--entry",
            "--title=새 값 입력",
            f"--text={FIELD_LABELS.get(field, field)} 값을 입력하세요. null 입력은 선택 필드에서만 허용됩니다.",
            f"--entry-text={json_text(row.get(field))}",
            "--width=720",
            check=False,
        )
        if new_value.returncode != 0:
            continue
        note = zenity(
            "--entry",
            "--title=수정 사유 입력",
            "--text=원문 근거 확인, 실무자 판단, 오류 정정 등 수정 사유를 입력하세요.",
            "--width=720",
            check=False,
        )
        if note.returncode != 0:
            continue
        try:
            event = update_rule_value(
                path=path,
                rule_id=rule_id,
                field=field,
                raw_value=new_value.stdout.strip(),
                reviewer=__import__("os").environ.get("USER", "practitioner"),
                note=note.stdout.strip(),
                dry_run=False,
            )
        except Exception as exc:  # pragma: no cover - GUI error path
            zenity("--error", "--title=룰 수정 실패", f"--text={exc}", "--width=720", check=False)
            continue
        zenity(
            "--info",
            "--title=룰 수정 완료",
            f"--text={rule_id}\n{FIELD_LABELS.get(field, field)} 값이 수정되었습니다.\n\n이전: {json_text(event['old_value'])}\n변경: {json_text(event['new_value'])}",
            "--width=720",
            check=False,
        )
        payload = load_manifest(path)
        rows = active_rows(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review active claim calculation rules")
    parser.add_argument("--rules-path", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--list-json", action="store_true")
    parser.add_argument("--show")
    parser.add_argument("--editable-fields")
    parser.add_argument("--set", dest="set_rule_id")
    parser.add_argument("--field")
    parser.add_argument("--value")
    parser.add_argument("--reviewer", default="practitioner")
    parser.add_argument("--note", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gui", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.gui:
            run_gui(args.rules_path, args.dry_run)
            return 0
        if args.list_json:
            list_json(args.rules_path)
            return 0
        if args.show:
            show_rule(args.rules_path, args.show)
            return 0
        if args.editable_fields:
            print_editable_fields(args.rules_path, args.editable_fields)
            return 0
        if args.set_rule_id:
            if not args.field or args.value is None:
                raise ValueError("--field and --value are required with --set")
            event = update_rule_value(
                path=args.rules_path,
                rule_id=args.set_rule_id,
                field=args.field,
                raw_value=args.value,
                reviewer=args.reviewer,
                note=args.note,
                dry_run=args.dry_run,
            )
            print(json.dumps(event, ensure_ascii=False, indent=2, default=str))
            return 0
        build_parser().print_help()
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
