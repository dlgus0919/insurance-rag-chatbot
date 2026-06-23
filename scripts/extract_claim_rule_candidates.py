#!/usr/bin/env python3
"""Extract source-backed claim rule candidates from policy chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.claim_calculation.rule_candidates import validate_candidate_record, write_jsonl


DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data/processed/chunks_v1_v2_combined.jsonl"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data/rules/review/candidates.jsonl"
RULE_SIGNAL_RE = re.compile(r"(공제|본인부담|한도|연간|통원|입원|처방|급여|비급여|세대|보상)")
RATIO_RE = re.compile(r"(?P<percent>\d{1,3})\s*%")
GENERATION_RE = re.compile(r"(?P<generation>[1-5])\s*세대")


def extract_candidates_from_text(
    *,
    text: str,
    doc_short: str,
    chunk_id: str,
    page: int | str | None,
    article: str | None,
) -> list[dict[str, Any]]:
    if not chunk_id or not RULE_SIGNAL_RE.search(text):
        return []
    ratio_match = RATIO_RE.search(text)
    generation_match = GENERATION_RE.search(text)
    if not ratio_match or not generation_match:
        return []
    percent = int(ratio_match.group("percent"))
    if percent <= 0 or percent > 100:
        return []
    generation = f"{generation_match.group('generation')}th"
    category = "급여" if "급여" in text and "비급여" not in text else "비급여" if "비급여" in text else "unknown"
    visit_type = "outpatient" if "통원" in text else "hospitalization" if "입원" in text else "unknown"
    category_key = "benefit" if category == "급여" else "nonpay" if category == "비급여" else "unknown"
    risk_flags = []
    if category == "unknown":
        risk_flags.append("category_scope_unclear")
    if visit_type == "unknown":
        risk_flags.append("visit_scope_unclear")
    copay_ratio = round(1 - (percent / 100), 4)
    digest = hashlib.sha1(f"{generation}|{category}|{visit_type}|{percent}|{chunk_id}".encode("utf-8")).hexdigest()[:12]
    rule_id = f"deductible.{generation}.{category_key}.{visit_type}.{digest}"
    source_key = f"policy_chunk:{chunk_id}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    candidate = {
        "candidate_id": f"rulecand.{rule_id}",
        "status": "pending",
        "rule_type": "deductible",
        "proposed_rule": {
            "rule_id": rule_id,
            "generation": generation,
            "category": category,
            "visit_type": visit_type,
            "facility_grade": "all",
            "copay_ratio": str(copay_ratio),
            "min_deductible": "0",
            "min_deductible_by_facility": {"clinic": "0", "hospital": "0", "general_hospital": "0", "tertiary_hospital": "0"},
            "per_visit_limit": None,
            "annual_limit": None,
            "annual_visit_limit": None,
            "description": f"{generation} {category} {visit_type}: 본인부담금 {int(copay_ratio * 100)}%",
            "source_doc": doc_short,
            "source_page": str(page or "unknown"),
            "source_clause": article or f"source_chunk_id:{chunk_id}",
            "source_chunk_id": chunk_id,
            "additional_source_refs": [],
            "source_status": "source_grounded",
            "approval_status": "candidate",
        },
        "proposed_links": {
            "rule_id": rule_id,
            "source_refs": [source_key],
            "ontology_refs": ["cov.indemnity_medical"],
            "graph_refs": [f"source_chunk:{chunk_id}"],
            "link_status": "candidate",
        },
        "source_refs": [{"kind": "policy_chunk", "doc_short": doc_short, "chunk_id": chunk_id, "page": page, "article": article}],
        "evidence_text": text.strip(),
        "extraction_reason": "세대, 보상 비율, 계산 rule 신호가 같은 근거 안에서 확인됨",
        "risk_flags": risk_flags,
        "created_at": now,
        "reviewed_at": None,
        "reviewer": None,
        "review_note": "",
    }
    validate_candidate_record(candidate)
    return [candidate]


def iter_policy_chunks(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    chunks: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        metadata = row.get("metadata") or {}
        chunks.append(
            {
                "text": str(row.get("text") or row.get("content") or ""),
                "doc_short": str(row.get("doc_short") or metadata.get("doc_short") or row.get("source") or metadata.get("source") or "unknown"),
                "chunk_id": str(row.get("chunk_id") or row.get("id") or metadata.get("chunk_id") or ""),
                "page": row.get("page") or metadata.get("page") or metadata.get("page_start"),
                "article": row.get("article") or row.get("heading") or metadata.get("article") or metadata.get("heading"),
            }
        )
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract claim rule candidates from policy evidence.")
    parser.add_argument("--index-jsonl", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()

    candidates: list[dict[str, Any]] = []
    for chunk in iter_policy_chunks(args.index_jsonl):
        candidates.extend(extract_candidates_from_text(**chunk))
        if args.limit and len(candidates) >= args.limit:
            candidates = candidates[: args.limit]
            break

    summary = {"candidate_count": len(candidates), "output": str(args.output), "dry_run": args.dry_run}
    if not args.dry_run:
        if args.output.exists() and not args.replace_existing:
            raise SystemExit(f"{args.output} exists; use --replace-existing")
        write_jsonl(args.output, candidates)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
