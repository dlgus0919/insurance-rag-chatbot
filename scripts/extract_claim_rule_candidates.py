#!/usr/bin/env python3
"""Extract source-backed claim rule candidates from policy chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from decimal import Decimal, InvalidOperation
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
KOREAN_AMOUNT_VALUES = {
    "3만원": "30000",
    "5만원": "50000",
    "20만원": "200000",
    "5천만원": "50000000",
}
FOURTH_MANUAL_THERAPY_CHUNK_IDS = (
    "약관_ch_002441",
    "약관_ch_002442",
    "약관_ch_002443",
)
_PAYOUT_SIGNAL_RE = re.compile(r"(보상|지급)")
_COPAY_SIGNAL_RE = re.compile(r"(공제|본인부담)")
_MONEY_RE = re.compile(r"(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>억원|천만원|백만원|만원|천원|원)")
_MONEY_UNITS = {
    "억원": Decimal("100000000"),
    "천만원": Decimal("10000000"),
    "백만원": Decimal("1000000"),
    "만원": Decimal("10000"),
    "천원": Decimal("1000"),
    "원": Decimal("1"),
}


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _ratio_as_copay(text: str, ratio_match: re.Match[str]) -> Decimal | None:
    """Resolve percentage semantics only when the nearby wording is explicit."""

    window = text[max(0, ratio_match.start() - 48) : min(len(text), ratio_match.end() + 48)]
    percent = Decimal(ratio_match.group("percent")) / Decimal("100")
    if _PAYOUT_SIGNAL_RE.search(window):
        return Decimal("1") - percent
    if _COPAY_SIGNAL_RE.search(window):
        return percent
    return None


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
    copay_ratio = _ratio_as_copay(text, ratio_match)
    if copay_ratio is None:
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
            "copay_ratio": _decimal_text(copay_ratio),
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


def _candidate_base(
    candidate_id: str,
    rule: dict[str, Any],
    chunk: dict[str, Any],
    evidence_text: str,
    operation: str = "add",
) -> dict[str, Any]:
    source_key = f"policy_chunk:{chunk['chunk_id']}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    candidate = {
        "candidate_id": candidate_id,
        "status": "pending",
        "rule_type": "deductible",
        "operation": operation,
        "target_rule_id": rule["rule_id"] if operation == "replace" else None,
        "proposed_rule": rule,
        "proposed_links": {
            "rule_id": rule["rule_id"],
            "source_refs": [source_key],
            "ontology_refs": ["cov.indemnity_medical"],
            "graph_refs": [f"source_chunk:{chunk['chunk_id']}"],
            "link_status": "candidate",
        },
        "source_refs": [
            {
                "kind": "policy_chunk",
                "doc_short": chunk["doc_short"],
                "chunk_id": chunk["chunk_id"],
                "page": chunk["page"],
                "article": chunk["article"],
            }
        ],
        "evidence_text": evidence_text.strip(),
        "extraction_reason": "첨부 명세 범위의 5세대 산정특례/3대비급여/MRI-MRA 보완 후보",
        "risk_flags": ["manual_review_required"],
        "created_at": now,
        "reviewed_at": None,
        "reviewer": None,
        "review_note": "",
    }
    validate_candidate_record(candidate)
    return candidate


def _deductible_rule(
    *,
    rule_id: str,
    category: str,
    visit_type: str,
    copay_ratio: str,
    min_deductible: str,
    per_visit_limit: str | None,
    annual_limit: str | None,
    description: str,
    chunk: dict[str, Any],
    special_calculation_status: str,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "generation": "5th",
        "category": category,
        "visit_type": visit_type,
        "facility_grade": "all",
        "copay_ratio": copay_ratio,
        "min_deductible": min_deductible,
        "min_deductible_by_facility": {
            "clinic": min_deductible,
            "hospital": min_deductible,
            "general_hospital": min_deductible,
            "tertiary_hospital": min_deductible,
        },
        "per_visit_limit": per_visit_limit,
        "annual_limit": annual_limit,
        "annual_visit_limit": None,
        "description": description,
        "special_calculation_status": special_calculation_status,
        "source_doc": chunk["doc_short"],
        "source_page": str(chunk["page"] or "unknown"),
        "source_clause": chunk["article"] or f"source_chunk_id:{chunk['chunk_id']}",
        "source_chunk_id": chunk["chunk_id"],
        "additional_source_refs": [],
        "source_status": "source_grounded",
        "approval_status": "candidate",
    }


def _compact(text: str) -> str:
    return "".join(text.split())


def _has_special_case_three_major_signal(text: str) -> bool:
    compact = _compact(text)
    return "산정특례" in compact and "3대비급여" in compact and "30%" in compact


def _has_mri_mra_signal(text: str) -> bool:
    compact = _compact(text).lower()
    return ("mri" in compact or "mra" in compact or "자기공명영상" in compact) and "50%" in compact


def _amount_from_text(text: str, expected_value: str) -> str | None:
    compact = _compact(text)
    for pattern, value in KOREAN_AMOUNT_VALUES.items():
        if pattern in compact and value == expected_value:
            return value
    return None


def _visit_rule_specs(text: str, outpatient_minimum: str) -> list[tuple[str, str, str | None, str | None]]:
    specs: list[tuple[str, str, str | None, str | None]] = [
        ("hospitalization", "0", None, _amount_from_text(text, "50000000")),
    ]
    outpatient_min = _amount_from_text(text, outpatient_minimum)
    outpatient_limit = _amount_from_text(text, "200000")
    if outpatient_min and outpatient_limit:
        specs.append(("outpatient", outpatient_min, outpatient_limit, None))
    return specs


def extract_special_case_5th_candidates(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        if _has_special_case_three_major_signal(text):
            for visit_type, min_deductible, per_visit_limit, annual_limit in _visit_rule_specs(text, "30000"):
                rule = _deductible_rule(
                    rule_id=f"deductible.5th.three_major_non_benefit.{visit_type}",
                    category="3대비급여",
                    visit_type=visit_type,
                    copay_ratio="0.3",
                    min_deductible=min_deductible,
                    per_visit_limit=per_visit_limit,
                    annual_limit=annual_limit,
                    description=f"5세대 산정특례 적용 3대비급여 {visit_type} 본인부담금 30%",
                    chunk=chunk,
                    special_calculation_status="applied",
                )
                candidates.append(_candidate_base(f"rulecand.replace.{rule['rule_id']}", rule, chunk, text, operation="replace"))
        if _has_mri_mra_signal(text):
            for visit_type, min_deductible, per_visit_limit, annual_limit in _visit_rule_specs(text, "50000"):
                rule = _deductible_rule(
                    rule_id=f"deductible.5th.mri_mra.{visit_type}",
                    category="비급여자기공명영상진단",
                    visit_type=visit_type,
                    copay_ratio="0.5",
                    min_deductible=min_deductible,
                    per_visit_limit=per_visit_limit,
                    annual_limit=annual_limit,
                    description=f"5세대 산정특례 미적용 비급여 자기공명영상진단 {visit_type} 본인부담금 50%",
                    chunk=chunk,
                    special_calculation_status="not_applied",
                )
                candidates.append(_candidate_base(f"rulecand.add.{rule['rule_id']}", rule, chunk, text, operation="add"))
    return candidates


def _chunk_map(chunks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(chunk.get("chunk_id") or ""): chunk for chunk in chunks if chunk.get("chunk_id")}


def _money_values(text: str) -> list[int]:
    values: list[int] = []
    for match in _MONEY_RE.finditer(text):
        try:
            amount = Decimal(match.group("number").replace(",", "")) * _MONEY_UNITS[match.group("unit")]
        except (InvalidOperation, KeyError):
            continue
        if amount > 0 and amount == amount.to_integral_value():
            values.append(int(amount))
    return values


def _manual_therapy_review_requirements(supporting_chunks: list[dict[str, Any]]) -> list[str] | None:
    support_text = " ".join(str(chunk.get("text") or "") for chunk in supporting_chunks)
    compact = _compact(support_text)
    requirements: list[str] = []
    if "최초" in compact and "10회" in compact and ("호전" in compact or "증상" in compact):
        requirements.append("최초 10회 이후 증상 호전 증빙 확인 필요")
    if ("동일" in compact or "당일" in compact) and "1회" in compact:
        requirements.append("동일 방문 복수 치료 횟수 확인 필요")
    return requirements if len(requirements) == 2 else None


def extract_fourth_manual_therapy_candidates(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create pending 4th-generation manual-therapy candidates from fixed evidence handles.

    The function only proposes rules when every required source chunk is present and
    the financial values can be read from the primary source. It never writes an
    active manifest or invents a rule from a partial match.
    """

    by_chunk_id = _chunk_map(chunks)
    if any(chunk_id not in by_chunk_id for chunk_id in FOURTH_MANUAL_THERAPY_CHUNK_IDS):
        return []

    primary = by_chunk_id[FOURTH_MANUAL_THERAPY_CHUNK_IDS[0]]
    supporting_chunks = [by_chunk_id[chunk_id] for chunk_id in FOURTH_MANUAL_THERAPY_CHUNK_IDS[1:]]
    primary_text = str(primary.get("text") or "")
    source_set_text = "\n".join(str(chunk.get("text") or "") for chunk in [primary, *supporting_chunks])
    compact_primary = _compact(primary_text)
    if not all(term in compact_primary for term in ("도수", "체외충격파", "증식")):
        return []

    ratio_match = next(
        (
            match
            for match in RATIO_RE.finditer(source_set_text)
            if _ratio_as_copay(source_set_text, match) is not None
        ),
        None,
    )
    if ratio_match is None:
        return []
    copay_ratio = _ratio_as_copay(source_set_text, ratio_match)
    if copay_ratio is None:
        return []
    # OCR chunk boundaries can split a date-like number and a currency unit.
    # Parse each source separately so adjacent chunks cannot form a false amount.
    money_values = [
        value
        for chunk in [primary, *supporting_chunks]
        for value in _money_values(str(chunk.get("text") or ""))
    ]
    if len(money_values) < 2:
        return []
    minimum = min(money_values)
    annual_limit = max(money_values)
    annual_visit_counts = [
        int(match.group("count"))
        for match in re.finditer(r"(?P<count>\d+)\s*회", source_set_text)
    ]
    if not annual_visit_counts or "한도" not in _compact(source_set_text):
        return []
    annual_visit_limit = max(annual_visit_counts)
    review_requirements = _manual_therapy_review_requirements(supporting_chunks)
    if review_requirements is None:
        return []

    additional_source_refs = list(FOURTH_MANUAL_THERAPY_CHUNK_IDS[1:])
    source_refs = [
        {
            "kind": "policy_chunk",
            "doc_short": str(chunk.get("doc_short") or "unknown"),
            "chunk_id": str(chunk["chunk_id"]),
            "page": chunk.get("page"),
            "article": chunk.get("article"),
        }
        for chunk in supporting_chunks
    ]
    evidence_text = "\n\n".join(str(chunk.get("text") or "").strip() for chunk in [primary, *supporting_chunks])
    candidates: list[dict[str, Any]] = []
    for visit_type in ("hospitalization", "outpatient"):
        rule_id = f"deductible.4th.three_major_manual.{visit_type}"
        rule = {
            "rule_id": rule_id,
            "generation": "4th",
            "category": "3대비급여_도수",
            "visit_type": visit_type,
            "facility_grade": "all",
            "copay_ratio": _decimal_text(copay_ratio),
            "min_deductible": str(minimum),
            "min_deductible_by_facility": {
                "clinic": str(minimum),
                "hospital": str(minimum),
                "general_hospital": str(minimum),
                "tertiary_hospital": str(minimum),
            },
            "per_visit_limit": None,
            "annual_limit": str(annual_limit),
            "annual_visit_limit": annual_visit_limit,
            "review_requirements": review_requirements,
            "description": (
                f"4세대 3대비급여 도수치료군: 1회당 {minimum:,}원과 "
                f"보장대상의료비 {int(copay_ratio * 100)}% 중 큰 금액, 연 {annual_limit:,}원·{annual_visit_limit}회"
            ),
            "source_doc": str(primary.get("doc_short") or "unknown"),
            "source_page": str(primary.get("page") or "unknown"),
            "source_clause": str(primary.get("article") or f"source_chunk_id:{primary['chunk_id']}"),
            "source_chunk_id": str(primary["chunk_id"]),
            "additional_source_refs": additional_source_refs,
            "source_status": "source_grounded",
            "approval_status": "candidate",
        }
        candidate = _candidate_base(f"rulecand.add.{rule_id}", rule, primary, evidence_text)
        candidate["source_refs"].extend(source_refs)
        candidate["proposed_links"]["source_refs"].extend(f"policy_chunk:{chunk_id}" for chunk_id in additional_source_refs)
        candidate["proposed_links"]["graph_refs"].extend(f"source_chunk:{chunk_id}" for chunk_id in additional_source_refs)
        candidate["extraction_reason"] = "4세대 도수치료군의 공제율, 최소공제, 연간 한도와 추가 증빙 조건을 원문 근거에서 분리 추출함"
        validate_candidate_record(candidate)
        candidates.append(candidate)
    return candidates


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
                "chunk_id": str(
                    row.get("chunk_id")
                    or metadata.get("source_chunk_id")
                    or metadata.get("canonical_chunk_id")
                    or metadata.get("chunk_id")
                    or row.get("id")
                    or ""
                ),
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
    parser.add_argument("--scope", choices=["generic", "special-case-5th", "fourth-manual-therapy"], default="generic")
    args = parser.parse_args()

    chunks = iter_policy_chunks(args.index_jsonl)
    if args.scope == "special-case-5th":
        candidates = extract_special_case_5th_candidates(chunks)
        if args.limit:
            candidates = candidates[: args.limit]
    elif args.scope == "fourth-manual-therapy":
        candidates = extract_fourth_manual_therapy_candidates(chunks)
        if args.limit:
            candidates = candidates[: args.limit]
    else:
        candidates = []
        for chunk in chunks:
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
