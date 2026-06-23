#!/usr/bin/env python3
"""Review and apply source-backed claim rule candidates."""

from __future__ import annotations

import argparse
import json
import shutil
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
