#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB_PATH = Path("data/index/graph/insurance_graph.sqlite")
DEFAULT_CSV_PATH = Path("reports/graph/one_disease_policy_clause_inventory.csv")
DEFAULT_MD_PATH = Path("reports/graph/one_disease_policy_clause_inventory.md")

ONE_DISEASE_KEYWORDS = (
    "하나의 질병",
    "동일한 질병",
    "같은 질병",
    "하나의 상해",
    "같은 상해",
)

CLAIM_UNIT_PATTERNS = {
    "하나의 질병": ("하나의 질병", "동일한 질병", "같은 질병"),
    "하나의 상해": ("하나의 상해", "같은 상해"),
    "하나의 통원": ("하나의 통원", "통원 1회", "하루에 같은 치료"),
    "하나의 입원": ("하나의 입원", "1회 입원", "계속 입원"),
    "하나의 질병수술": ("하나의 질병수술", "질병수술비만 지급"),
    "하나의 후유장해 지급한도": ("후유장해보험금은", "후유장해보험가입금액을 한도"),
}

GROUPING_CRITERIA_PATTERNS = {
    "발생 원인 동일": ("발생 원인이 동일",),
    "의학상 중요한 관련": ("의학상 중요한 관련",),
    "2회 이상 치료": ("2회 이상 치료",),
    "치료 중 발생한 합병증": ("치료 중에 발생된 합병증", "치료 중 발생한 합병증"),
    "새로 발견된 질병": ("새로 발견된 질병",),
    "의학상 관련 없는 여러 질병": ("의학상 관련이 없는 여러 종류의 질병",),
    "같은 치료 목적": ("같은 치료를 목적", "같은 치료 목적"),
    "동일 질병 다중 수술": ("동일한 질병으로 두 종류 이상의 질병수술",),
    "같은 종류 수술 반복": ("같은 종류의 수술을 2회 이상",),
    "전환/재개 전후 계속 치료": ("전환전", "재개전", "전환∙재개", "전환·재개"),
    "180일 보상기간": ("180일",),
    "방문 90회/처방전 90건": ("90회", "90건"),
}

LINK_EDGE_TYPES = (
    "HAS_TOPIC",
    "APPLIES_WHEN",
    "HAS_DECISION",
    "REQUIRES_EVIDENCE",
    "RELATES_TO_DIAGNOSIS",
    "RELATES_TO_COMPLICATION",
    "APPLIES_TO_GENERATION",
    "APPLIES_TO_VISIT",
    "APPLIES_TO_FACILITY",
    "HAS_REVIEW_ACTION",
    "HAS_EXCLUSION_REASON",
    "HAS_BENEFIT_LIMIT",
    "HAS_DEDUCTIBLE_RULE",
    "REQUIRES_DOCUMENT",
    "HAS_COORDINATION_RULE",
    "HAS_GENERATION_RULE",
)


@dataclass
class InventoryRow:
    node_id: str
    doc_short: str
    page_start: str
    page_end: str
    clause_title: str
    clause_type: str
    decision_polarity: str
    source_priority: str
    claim_units: list[str] = field(default_factory=list)
    grouping_criteria: list[str] = field(default_factory=list)
    linked_topics: list[str] = field(default_factory=list)
    linked_conditions: list[str] = field(default_factory=list)
    linked_limits: list[str] = field(default_factory=list)
    linked_deductibles: list[str] = field(default_factory=list)
    linked_review_actions: list[str] = field(default_factory=list)
    linked_documents: list[str] = field(default_factory=list)
    linked_complications: list[str] = field(default_factory=list)
    linked_generations: list[str] = field(default_factory=list)
    linked_visits: list[str] = field(default_factory=list)
    excerpt: str = ""

    def as_csv_row(self) -> dict[str, str]:
        return {
            "node_id": self.node_id,
            "doc_short": self.doc_short,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "clause_title": self.clause_title,
            "clause_type": self.clause_type,
            "decision_polarity": self.decision_polarity,
            "source_priority": self.source_priority,
            "claim_units": "; ".join(self.claim_units),
            "grouping_criteria": "; ".join(self.grouping_criteria),
            "linked_topics": "; ".join(self.linked_topics),
            "linked_conditions": "; ".join(self.linked_conditions),
            "linked_limits": "; ".join(self.linked_limits),
            "linked_deductibles": "; ".join(self.linked_deductibles),
            "linked_review_actions": "; ".join(self.linked_review_actions),
            "linked_documents": "; ".join(self.linked_documents),
            "linked_complications": "; ".join(self.linked_complications),
            "linked_generations": "; ".join(self.linked_generations),
            "linked_visits": "; ".join(self.linked_visits),
            "excerpt": " ".join(self.excerpt.split()),
        }


def _load_properties(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        loaded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _match_labels(text: str, mapping: dict[str, tuple[str, ...]]) -> list[str]:
    return [label for label, needles in mapping.items() if any(needle in text for needle in needles)]


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _fetch_linked_names(conn: sqlite3.Connection, node_id: str) -> dict[str, list[str]]:
    linked: dict[str, list[str]] = {edge_type: [] for edge_type in LINK_EDGE_TYPES}
    rows = conn.execute(
        """
        SELECT e.edge_type, n.canonical_name
        FROM graph_edges e
        JOIN graph_nodes n ON e.target_node_id = n.node_id
        WHERE e.source_node_id = ?
          AND e.edge_type IN ({})
        ORDER BY e.edge_type, n.canonical_name
        """.format(",".join("?" for _ in LINK_EDGE_TYPES)),
        (node_id, *LINK_EDGE_TYPES),
    ).fetchall()
    for row in rows:
        linked[row["edge_type"]].append(row["canonical_name"])
    return {key: _dedupe(values) for key, values in linked.items()}


def collect_inventory(db_path: Path) -> list[InventoryRow]:
    if not db_path.exists():
        raise FileNotFoundError(f"Graph DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        where_parts = []
        params: list[str] = []
        for keyword in ONE_DISEASE_KEYWORDS:
            where_parts.append("(canonical_name LIKE ? OR properties_json LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        rows = conn.execute(
            f"""
            SELECT node_id, canonical_name, properties_json
            FROM graph_nodes
            WHERE node_type = 'PolicyClause'
              AND ({' OR '.join(where_parts)})
            ORDER BY
              json_extract(properties_json, '$.doc_short'),
              CAST(json_extract(properties_json, '$.page_start') AS INTEGER),
              node_id
            """,
            params,
        ).fetchall()

        inventory: list[InventoryRow] = []
        for row in rows:
            props = _load_properties(row["properties_json"])
            excerpt = str(props.get("excerpt") or "")
            text_for_match = f"{row['canonical_name']} {excerpt} {json.dumps(props, ensure_ascii=False)}"
            linked = _fetch_linked_names(conn, row["node_id"])
            inventory.append(
                InventoryRow(
                    node_id=row["node_id"],
                    doc_short=str(props.get("doc_short") or ""),
                    page_start=str(props.get("page_start") or ""),
                    page_end=str(props.get("page_end") or props.get("page_start") or ""),
                    clause_title=str(props.get("clause_title") or row["canonical_name"] or ""),
                    clause_type=str(props.get("clause_type") or ""),
                    decision_polarity=str(props.get("decision_polarity") or ""),
                    source_priority=str(props.get("source_priority") or ""),
                    claim_units=_match_labels(text_for_match, CLAIM_UNIT_PATTERNS),
                    grouping_criteria=_match_labels(text_for_match, GROUPING_CRITERIA_PATTERNS),
                    linked_topics=linked["HAS_TOPIC"],
                    linked_conditions=linked["APPLIES_WHEN"],
                    linked_limits=linked["HAS_BENEFIT_LIMIT"],
                    linked_deductibles=linked["HAS_DEDUCTIBLE_RULE"],
                    linked_review_actions=linked["HAS_REVIEW_ACTION"],
                    linked_documents=linked["REQUIRES_DOCUMENT"],
                    linked_complications=linked["RELATES_TO_COMPLICATION"],
                    linked_generations=linked["APPLIES_TO_GENERATION"],
                    linked_visits=linked["APPLIES_TO_VISIT"],
                    excerpt=excerpt,
                )
            )
        return inventory
    finally:
        conn.close()


def write_csv(rows: list[InventoryRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(InventoryRow("", "", "", "", "", "", "", "").as_csv_row().keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv_row())


def write_markdown(rows: list[InventoryRow], path: Path, csv_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc_counts: dict[str, int] = {}
    unit_counts: dict[str, int] = {}
    criterion_counts: dict[str, int] = {}
    for row in rows:
        doc_counts[row.doc_short] = doc_counts.get(row.doc_short, 0) + 1
        for unit in row.claim_units:
            unit_counts[unit] = unit_counts.get(unit, 0) + 1
        for criterion in row.grouping_criteria:
            criterion_counts[criterion] = criterion_counts.get(criterion, 0) + 1

    lines = [
        "# One Disease Policy Clause Inventory",
        "",
        "이 보고서는 GraphDB의 `PolicyClause` 중 `하나의 질병`, `동일한 질병`, `하나의 상해` 관련 조항을 추출한 Phase 1 산출물이다.",
        "",
        f"- CSV: `{csv_path}`",
        f"- 총 조항 수: {len(rows)}",
        "",
        "## 문서별 건수",
        "",
    ]
    for doc, count in sorted(doc_counts.items()):
        lines.append(f"- `{doc}`: {count}")
    lines.extend(["", "## Claim Unit 후보", ""])
    for unit, count in sorted(unit_counts.items()):
        lines.append(f"- `{unit}`: {count}")
    lines.extend(["", "## Grouping Criterion 후보", ""])
    for criterion, count in sorted(criterion_counts.items()):
        lines.append(f"- `{criterion}`: {count}")
    lines.extend(["", "## 조항 목록", ""])
    for row in rows:
        excerpt = " ".join(row.excerpt.split())
        if len(excerpt) > 180:
            excerpt = excerpt[:177] + "..."
        lines.extend(
            [
                f"### {row.doc_short} p.{row.page_start} - {row.clause_title}",
                "",
                f"- node_id: `{row.node_id}`",
                f"- claim_units: {', '.join(row.claim_units) or '-'}",
                f"- grouping_criteria: {', '.join(row.grouping_criteria) or '-'}",
                f"- linked_limits: {', '.join(row.linked_limits) or '-'}",
                f"- linked_review_actions: {', '.join(row.linked_review_actions) or '-'}",
                f"- excerpt: {excerpt}",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory one-disease policy clauses from the GraphDB.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    parser.add_argument("--fail-under", type=int, default=1)
    args = parser.parse_args()

    rows = collect_inventory(args.db)
    write_csv(rows, args.csv)
    write_markdown(rows, args.md, args.csv)
    print(f"one_disease_policy_clause_inventory rows={len(rows)} csv={args.csv} md={args.md}")
    if len(rows) < args.fail_under:
        print(f"expected at least {args.fail_under} rows, got {len(rows)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
