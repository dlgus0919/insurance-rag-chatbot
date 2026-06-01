from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.inventory_one_disease_policy_clauses import collect_inventory, write_csv, write_markdown


def _make_graph_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE graph_nodes (
            node_id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            properties_json TEXT,
            confidence REAL,
            created_by TEXT,
            updated_at TEXT
        );
        CREATE TABLE graph_edges (
            edge_id TEXT PRIMARY KEY,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            properties_json TEXT,
            confidence REAL,
            source_evidence_id TEXT,
            created_by TEXT,
            updated_at TEXT
        );
        """
    )
    conn.execute(
        """
        INSERT INTO graph_nodes VALUES (
            'clause_one_disease', 'PolicyClause', '제3조(보장종목별 보상내용)',
            '제3조보장종목별보상내용',
            '{"doc_short":"표준약관","page_start":350,"page_end":350,"clause_title":"하나의 질병 정의","clause_type":"definition","decision_polarity":"coverage","source_priority":"high","excerpt":"하나의 질병이란 발생 원인이 동일한 질병이며 의학상 중요한 관련이 있는 질병은 하나의 질병으로 간주합니다. 질병의 치료 중에 발생된 합병증 또는 새로 발견된 질병의 치료가 병행된 경우도 검토합니다."}',
            1.0, 'test', ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO graph_nodes VALUES (
            'benefit_limit_visit', 'BenefitLimit', '통원 1회 한도',
            '통원1회한도', '{}', 1.0, 'test', ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO graph_edges VALUES (
            'edge_limit', 'clause_one_disease', 'benefit_limit_visit',
            'HAS_BENEFIT_LIMIT', '{}', 1.0, NULL, 'test', ''
        )
        """
    )
    conn.commit()
    conn.close()


def test_collect_inventory_extracts_claim_units_and_criteria(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    _make_graph_db(db_path)

    rows = collect_inventory(db_path)

    assert len(rows) == 1
    row = rows[0]
    assert row.doc_short == "표준약관"
    assert "하나의 질병" in row.claim_units
    assert "발생 원인 동일" in row.grouping_criteria
    assert "의학상 중요한 관련" in row.grouping_criteria
    assert "치료 중 발생한 합병증" in row.grouping_criteria
    assert row.linked_limits == ["통원 1회 한도"]


def test_write_outputs(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    csv_path = tmp_path / "inventory.csv"
    md_path = tmp_path / "inventory.md"
    _make_graph_db(db_path)

    rows = collect_inventory(db_path)
    write_csv(rows, csv_path)
    write_markdown(rows, md_path, csv_path)

    assert "claim_units" in csv_path.read_text(encoding="utf-8")
    markdown = md_path.read_text(encoding="utf-8")
    assert "One Disease Policy Clause Inventory" in markdown
    assert "`표준약관`: 1" in markdown
