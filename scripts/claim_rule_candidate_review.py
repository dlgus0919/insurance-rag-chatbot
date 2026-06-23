#!/usr/bin/env python3
"""Review and apply source-backed claim rule candidates."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.claim_calculation.rule_candidates import build_apply_plan, load_jsonl, validate_candidate_record, write_jsonl
from src.claim_calculation.rule_registry import ClaimRuleRegistry


DEFAULT_CANDIDATES = PROJECT_ROOT / "data/rules/review/candidates.jsonl"
DEFAULT_REVIEW_LOG = PROJECT_ROOT / "data/rules/review/review_log.jsonl"
DEFAULT_RULES = PROJECT_ROOT / "data/rules/claim_deductible_rules.active.json"
DEFAULT_LINKS = PROJECT_ROOT / "data/rules/rule_links.active.json"
SECTIONS = {"deductible": "rules", "prescription": "prescription_rules", "special": "special_rules"}
EDITABLE_FIELDS = {
    "proposed_rule.copay_ratio",
    "proposed_rule.min_deductible",
    "proposed_rule.per_visit_limit",
    "proposed_rule.annual_limit",
    "proposed_rule.annual_visit_limit",
    "proposed_rule.source_chunk_id",
    "proposed_rule.additional_source_refs",
    "proposed_links.source_refs",
    "proposed_links.ontology_refs",
    "proposed_links.graph_refs",
    "review_note",
}
FIELD_LABELS = {
    "proposed_rule.copay_ratio": "공제율",
    "proposed_rule.min_deductible": "최소 공제금",
    "proposed_rule.per_visit_limit": "회당 한도",
    "proposed_rule.annual_limit": "연간 한도",
    "proposed_rule.annual_visit_limit": "연간 횟수 한도",
    "proposed_rule.source_chunk_id": "근거 chunk_id",
    "proposed_rule.additional_source_refs": "추가 근거",
    "proposed_links.source_refs": "source link",
    "proposed_links.ontology_refs": "ontology link",
    "proposed_links.graph_refs": "graph link",
    "review_note": "검토 메모",
}


def status_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in ("pending", "approved", "rejected", "applied")}
    for record in records:
        counts[str(record.get("status"))] = counts.get(str(record.get("status")), 0) + 1
    counts["total"] = len(records)
    return counts


def find_candidate(records: list[dict[str, Any]], candidate_id: str) -> dict[str, Any]:
    for record in records:
        if record.get("candidate_id") == candidate_id:
            return record
    raise ValueError(f"candidate not found: {candidate_id}")


def append_log(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def decide_candidate(
    records: list[dict[str, Any]],
    candidate_id: str,
    decision: str,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    status = {"approve": "approved", "reject": "rejected"}[decision]
    record = find_candidate(records, candidate_id)
    record["status"] = status
    record["reviewer"] = reviewer
    record["review_note"] = reason
    record["reviewed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if status == "approved":
        validate_candidate_record(record)
    return {"event": "candidate_decision", "candidate_id": candidate_id, "decision": status, "reviewer": reviewer, "reason": reason}


def edit_candidate(records: list[dict[str, Any]], candidate_id: str, field: str, raw_value: str, note: str) -> dict[str, Any]:
    if field not in EDITABLE_FIELDS:
        raise ValueError(f"field is not editable: {field}")
    record = find_candidate(records, candidate_id)
    old_value = _get_nested(record, field)
    new_value = _parse_value(raw_value)
    _set_nested(record, field, new_value)
    record["review_note"] = note or record.get("review_note", "")
    validate_candidate_record(record)
    return {"event": "candidate_edit", "candidate_id": candidate_id, "field": field, "old_value": old_value, "new_value": new_value, "note": note}


def apply_candidates(
    *,
    candidates_path: Path,
    review_log_path: Path,
    rules_path: Path,
    links_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    candidates = load_jsonl(candidates_path)
    rules_payload = json.loads(rules_path.read_text(encoding="utf-8"))
    links = _load_links(links_path)
    active_rules = []
    for section in ("rules", "prescription_rules", "special_rules"):
        active_rules.extend(rules_payload.get(section) or [])
    plan = build_apply_plan(active_rules=active_rules, active_links=links, candidates=candidates)
    summary = {
        "rules_to_add": [rule["rule_id"] for rule in plan.rules_to_add],
        "links_to_add": [link["rule_id"] for link in plan.links_to_add],
        "applied_candidate_ids": plan.applied_candidate_ids,
        "dry_run": dry_run,
    }
    if dry_run or not plan.rules_to_add:
        return summary

    updated_rules = deepcopy(rules_payload)
    approved = [candidate for candidate in candidates if candidate.get("candidate_id") in plan.applied_candidate_ids]
    by_id = {rule["rule_id"]: rule for rule in plan.rules_to_add}
    for candidate in approved:
        section = SECTIONS[str(candidate["rule_type"])]
        updated_rules.setdefault(section, []).append(by_id[candidate["proposed_rule"]["rule_id"]])
    _validate_rules_payload(updated_rules)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _backup(rules_path, now)
    _backup(links_path, now)
    rules_path.write_text(json.dumps(updated_rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    links_path.parent.mkdir(parents=True, exist_ok=True)
    links_path.write_text(json.dumps(links + plan.links_to_add, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for candidate in approved:
        candidate["status"] = "applied"
        candidate["applied_at"] = now
    write_jsonl(candidates_path, candidates)
    append_log(review_log_path, {"event": "candidate_apply", "reviewed_at": now, **summary})
    return summary


def _load_links(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("rule link manifest must be a list")
    return [row for row in data if isinstance(row, dict)]


def _backup(path: Path, timestamp: str) -> None:
    if not path.exists():
        return
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = timestamp.replace(":", "").replace("+", "Z")
    shutil.copy2(path, backup_dir / f"{path.stem}.{safe_ts}{path.suffix}")


def _validate_rules_payload(payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False)
        tmp_path = Path(fp.name)
    try:
        ClaimRuleRegistry.from_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _parse_value(raw_value: str) -> Any:
    text = raw_value.strip()
    if text.lower() in {"none", "null"}:
        return None
    if text.startswith("[") or text.startswith("{"):
        return json.loads(text)
    return text


def _get_nested(record: dict[str, Any], field: str) -> Any:
    target: Any = record
    for part in field.split("."):
        target = target.get(part)
    return target


def _set_nested(record: dict[str, Any], field: str, value: Any) -> None:
    parts = field.split(".")
    target = record
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def json_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return "null"
    return str(value)


def candidate_summary(record: dict[str, Any]) -> str:
    rule = record.get("proposed_rule") or {}
    return " ".join(
        part
        for part in (
            str(rule.get("generation") or ""),
            str(rule.get("category") or ""),
            str(rule.get("visit_type") or ""),
            str(rule.get("facility_grade") or ""),
        )
        if part
    )


def format_candidate_detail(record: dict[str, Any]) -> str:
    rule = record.get("proposed_rule") or {}
    links = record.get("proposed_links") or {}
    lines = [
        f"후보 ID: {record.get('candidate_id')}",
        f"상태: {record.get('status')}",
        f"룰 ID: {rule.get('rule_id')}",
        f"구분: {candidate_summary(record)}",
        "",
        "제안 값:",
        f"- 공제율/지급률: {json_text(rule.get('copay_ratio') or rule.get('payout_ratio'))}",
        f"- 최소 공제금: {json_text(rule.get('min_deductible') or rule.get('deductible_amount'))}",
        f"- 회당 한도: {json_text(rule.get('per_visit_limit'))}",
        f"- 연간 한도: {json_text(rule.get('annual_limit'))}",
        "",
        "근거:",
        f"- 문서: {rule.get('source_doc', '')}",
        f"- 페이지: {rule.get('source_page', '')}",
        f"- 조항: {rule.get('source_clause', '')}",
        f"- chunk_id: {rule.get('source_chunk_id', '')}",
        f"- source refs: {json_text(links.get('source_refs') or [])}",
        f"- ontology refs: {json_text(links.get('ontology_refs') or [])}",
        "",
        "원문 근거:",
        str(record.get("evidence_text") or ""),
        "",
        "실무자 판단 기준:",
        "- 승인: 원문 근거와 제안 값이 일치하고 계산 룰로 쓰기에 모호성이 낮을 때 선택합니다.",
        "- 수정: 값이나 source/ontology 연결이 맞지만 일부 필드 정정이 필요할 때 선택합니다.",
        "- 거절: 근거가 불충분하거나 지급 판단을 안전하게 자동화하기 어렵다고 판단될 때 선택합니다.",
    ]
    return "\n".join(lines)


def zenity(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["zenity", *args], text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "zenity cancelled")
    return result


def require_gui(dry_run: bool) -> None:
    if dry_run:
        return
    import os

    if not (sys.platform.startswith("linux") and ("DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ)):
        raise RuntimeError("DISPLAY/WAYLAND_DISPLAY is not set. Run this from the DGX desktop session.")
    if shutil.which("zenity") is None:
        raise RuntimeError("zenity is required for rule candidate review GUI")


def list_height(row_count: int) -> int:
    return max(340, min(700, 190 + row_count * 34))


def run_gui(args: argparse.Namespace) -> None:
    require_gui(args.dry_run)
    records = load_jsonl(args.candidates)
    if args.dry_run:
        print(f"candidate_count={len(records)}")
        if records:
            print(format_candidate_detail(records[0]))
        return
    while True:
        records = load_jsonl(args.candidates)
        rows = [record for record in records if record.get("status") in {"pending", "approved"}]
        if not rows:
            zenity("--info", "--title=액티브 룰 신규 후보", "--text=검토할 룰 후보가 없습니다.", "--width=560", check=False)
            return
        list_args = [
            "--list",
            "--title=액티브 룰 신규 후보",
            "--text=문서 근거에서 자동 추출된 계산 룰 후보입니다. 값을 확인한 뒤 승인/수정/거절하세요.",
            "--width=980",
            f"--height={list_height(len(rows))}",
            "--column=candidate_id",
            "--column=상태",
            "--column=구분",
            "--column=설명",
            "--print-column=1",
        ]
        for record in rows:
            rule = record.get("proposed_rule") or {}
            list_args.extend(
                [
                    str(record.get("candidate_id")),
                    str(record.get("status")),
                    candidate_summary(record),
                    str(rule.get("description", "")),
                ]
            )
        selected = zenity(*list_args, check=False)
        if selected.returncode != 0 or not selected.stdout.strip():
            return
        candidate_id = selected.stdout.strip()
        record = find_candidate(load_jsonl(args.candidates), candidate_id)
        action = zenity(
            "--list",
            "--title=후보 처리 선택",
            f"--text={format_candidate_detail(record)}",
            "--width=940",
            "--height=700",
            "--column=action",
            "--column=처리",
            "--hide-column=1",
            "--print-column=1",
            "approve",
            "승인",
            "edit",
            "값/연결 수정",
            "reject",
            "거절",
            "apply",
            "승인 후보 적용",
            check=False,
        )
        if action.returncode != 0 or not action.stdout.strip():
            continue
        selected_action = action.stdout.strip()
        try:
            if selected_action in {"approve", "reject"}:
                reason = zenity(
                    "--entry",
                    "--title=처리 사유 입력",
                    "--text=실무자 판단 사유를 입력하세요.",
                    "--width=720",
                    check=False,
                )
                if reason.returncode != 0:
                    continue
                records = load_jsonl(args.candidates)
                event = decide_candidate(records, candidate_id, selected_action, args.reviewer, reason.stdout.strip())
                write_jsonl(args.candidates, records)
                append_log(args.review_log, event)
            elif selected_action == "edit":
                _gui_edit_candidate(args, candidate_id)
            elif selected_action == "apply":
                summary = apply_candidates(
                    candidates_path=args.candidates,
                    review_log_path=args.review_log,
                    rules_path=args.rules_path,
                    links_path=args.links_path,
                    dry_run=False,
                )
                zenity(
                    "--info",
                    "--title=후보 적용 완료",
                    f"--text={json.dumps(summary, ensure_ascii=False, indent=2)}",
                    "--width=760",
                    check=False,
                )
        except Exception as exc:  # pragma: no cover - GUI error path
            zenity("--error", "--title=룰 후보 처리 실패", f"--text={exc}", "--width=760", check=False)


def _gui_edit_candidate(args: argparse.Namespace, candidate_id: str) -> None:
    record = find_candidate(load_jsonl(args.candidates), candidate_id)
    field_args = [
        "--list",
        "--title=수정 항목 선택",
        f"--text={format_candidate_detail(record)}",
        "--width=940",
        "--height=700",
        "--column=field",
        "--column=표시명",
        "--column=현재값",
        "--hide-column=1",
        "--print-column=1",
    ]
    for field in sorted(EDITABLE_FIELDS):
        field_args.extend([field, FIELD_LABELS.get(field, field), json_text(_get_nested(record, field))])
    picked = zenity(*field_args, check=False)
    if picked.returncode != 0 or not picked.stdout.strip():
        return
    field = picked.stdout.strip()
    value = zenity(
        "--entry",
        "--title=새 값 입력",
        f"--text={FIELD_LABELS.get(field, field)} 값을 입력하세요. 배열/객체는 JSON 형식으로 입력합니다.",
        f"--entry-text={json_text(_get_nested(record, field))}",
        "--width=760",
        check=False,
    )
    if value.returncode != 0:
        return
    note = zenity("--entry", "--title=수정 사유", "--text=수정 사유를 입력하세요.", "--width=720", check=False)
    if note.returncode != 0:
        return
    records = load_jsonl(args.candidates)
    event = edit_candidate(records, candidate_id, field, value.stdout.strip(), note.stdout.strip())
    write_jsonl(args.candidates, records)
    append_log(args.review_log, event)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review claim rule candidates")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--review-log", type=Path, default=DEFAULT_REVIEW_LOG)
    parser.add_argument("--rules-path", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--links-path", type=Path, default=DEFAULT_LINKS)
    parser.add_argument("--pending-count", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--list-json", action="store_true")
    parser.add_argument("--show")
    parser.add_argument("--decide")
    parser.add_argument("--decision", choices=["approve", "reject"])
    parser.add_argument("--reviewer", default="practitioner")
    parser.add_argument("--reason", default="")
    parser.add_argument("--edit")
    parser.add_argument("--field")
    parser.add_argument("--value")
    parser.add_argument("--note", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gui", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.gui:
        run_gui(args)
        return 0
    records = load_jsonl(args.candidates)
    if args.pending_count:
        print(sum(1 for record in records if record.get("status") == "pending"))
        return 0
    if args.summary:
        print(json.dumps(status_counts(records), ensure_ascii=False, indent=2))
        return 0
    if args.list_json:
        for record in records:
            print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return 0
    if args.show:
        print(json.dumps(find_candidate(records, args.show), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.decide:
        if not args.decision:
            raise SystemExit("--decision is required with --decide")
        event = decide_candidate(records, args.decide, args.decision, args.reviewer, args.reason)
        write_jsonl(args.candidates, records)
        append_log(args.review_log, event)
        print(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.edit:
        if not args.field or args.value is None:
            raise SystemExit("--field and --value are required with --edit")
        event = edit_candidate(records, args.edit, args.field, args.value, args.note)
        write_jsonl(args.candidates, records)
        append_log(args.review_log, event)
        print(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.apply:
        print(json.dumps(apply_candidates(candidates_path=args.candidates, review_log_path=args.review_log, rules_path=args.rules_path, links_path=args.links_path, dry_run=args.dry_run), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
