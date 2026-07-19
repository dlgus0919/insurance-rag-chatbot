from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from src.graph.schema import Alias, Edge, Evidence, Node


def check_readonly(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if getattr(self, "readonly", False):
            raise PermissionError(f"Method '{method.__name__}' is not allowed in read-only mode.")
        return method(self, *args, **kwargs)
    return wrapper


class GraphStore:
    def __init__(
        self,
        db_path: str | Path,
        build_mode: bool = False,
        readonly: bool = False,
        immutable: bool = False,
    ):
        self.db_path = Path(db_path)
        self.readonly = readonly
        self.immutable = immutable
        if self.immutable and not self.readonly:
            raise ValueError("immutable mode requires read-only mode")
        if self.readonly:
            if not self.db_path.exists():
                raise FileNotFoundError(f"Database file not found at {self.db_path} for read-only mode.")
            # SQLITE URI read-only 연결
            uri = f"file:{self.db_path.resolve()}?mode=ro"
            if self.immutable:
                uri += "&immutable=1"
            self.conn = sqlite3.connect(uri, uri=True)
        else:
            self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_db(build_mode=build_mode)

    def _init_db(self, build_mode: bool = False) -> None:
        """데이터베이스 스키마와 인덱스를 생성한다."""
        cursor = self.conn.cursor()

        # Foreign key 제약 활성화 및 성능 최적화 PRAGMA 설정
        cursor.execute("PRAGMA foreign_keys = ON;")
        if self.readonly:
            return
        if build_mode:
            cursor.execute("PRAGMA synchronous = OFF;")
            cursor.execute("PRAGMA journal_mode = WAL;")
        else:
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("PRAGMA journal_mode = WAL;")

        # 테이블 생성
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
          node_id TEXT PRIMARY KEY,
          node_type TEXT NOT NULL,
          canonical_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          properties_json TEXT NOT NULL DEFAULT '{}',
          confidence REAL NOT NULL DEFAULT 1.0,
          created_by TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS graph_aliases (
          alias_id TEXT PRIMARY KEY,
          node_id TEXT NOT NULL,
          alias TEXT NOT NULL,
          normalized_alias TEXT NOT NULL,
          source TEXT NOT NULL,
          confidence REAL NOT NULL DEFAULT 1.0,
          FOREIGN KEY(node_id) REFERENCES graph_nodes(node_id) ON DELETE CASCADE
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS graph_edges (
          edge_id TEXT PRIMARY KEY,
          source_node_id TEXT NOT NULL,
          target_node_id TEXT NOT NULL,
          edge_type TEXT NOT NULL,
          properties_json TEXT NOT NULL DEFAULT '{}',
          confidence REAL NOT NULL DEFAULT 1.0,
          source_evidence_id TEXT,
          created_by TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(source_node_id) REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
          FOREIGN KEY(target_node_id) REFERENCES graph_nodes(node_id) ON DELETE CASCADE
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS graph_evidence (
          evidence_id TEXT PRIMARY KEY,
          chunk_id TEXT,
          canonical_chunk_id TEXT,
          doc_short TEXT NOT NULL,
          doc_name TEXT,
          pdf_filename TEXT,
          page_start INTEGER,
          page_end INTEGER,
          source_version TEXT,
          source_method TEXT,
          table_id TEXT,
          row_index INTEGER,
          row_text TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          confidence REAL NOT NULL DEFAULT 1.0
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS graph_node_evidence (
          node_id TEXT NOT NULL,
          evidence_id TEXT NOT NULL,
          role TEXT NOT NULL,
          PRIMARY KEY(node_id, evidence_id, role),
          FOREIGN KEY(node_id) REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
          FOREIGN KEY(evidence_id) REFERENCES graph_evidence(evidence_id) ON DELETE CASCADE
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS graph_edge_evidence (
          edge_id TEXT NOT NULL,
          evidence_id TEXT NOT NULL,
          role TEXT NOT NULL,
          PRIMARY KEY(edge_id, evidence_id, role),
          FOREIGN KEY(edge_id) REFERENCES graph_edges(edge_id) ON DELETE CASCADE,
          FOREIGN KEY(evidence_id) REFERENCES graph_evidence(evidence_id) ON DELETE CASCADE
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS graph_build_manifest (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """)

        # 필수 인덱스 생성
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_nodes_type_norm ON graph_nodes(node_type, normalized_name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_nodes_normalized_name ON graph_nodes(normalized_name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_aliases_norm ON graph_aliases(normalized_alias);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_type_src ON graph_edges(edge_type, source_node_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_type_dst ON graph_edges(edge_type, target_node_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_node_id, edge_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_node_id, edge_type);")
        existing_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(graph_evidence)")}
        if "canonical_chunk_id" not in existing_columns:
            cursor.execute("ALTER TABLE graph_evidence ADD COLUMN canonical_chunk_id TEXT;")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_evidence_chunk ON graph_evidence(chunk_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_evidence_canonical_chunk ON graph_evidence(canonical_chunk_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_evidence_doc_page ON graph_evidence(doc_short, page_start);")

        self.conn.commit()

    @check_readonly
    def upsert_node(self, node: Node) -> None:
        """노드를 데이터베이스에 삽입하거나 이미 존재하는 경우 덮어쓴다."""
        cursor = self.conn.cursor()
        now_str = datetime.now().isoformat()
        node.updated_at = now_str

        cursor.execute(
            """
            INSERT INTO graph_nodes (node_id, node_type, canonical_name, normalized_name, properties_json, confidence, created_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                node_type = excluded.node_type,
                canonical_name = excluded.canonical_name,
                normalized_name = excluded.normalized_name,
                properties_json = excluded.properties_json,
                confidence = excluded.confidence,
                updated_at = excluded.updated_at;
            """,
            node.to_db_row()
        )

    @check_readonly
    def upsert_edge(self, edge: Edge) -> None:
        """엣지를 데이터베이스에 삽입하거나 이미 존재하는 경우 덮어쓴다."""
        cursor = self.conn.cursor()
        now_str = datetime.now().isoformat()
        edge.updated_at = now_str

        cursor.execute(
            """
            INSERT INTO graph_edges (edge_id, source_node_id, target_node_id, edge_type, properties_json, confidence, source_evidence_id, created_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(edge_id) DO UPDATE SET
                source_node_id = excluded.source_node_id,
                target_node_id = excluded.target_node_id,
                edge_type = excluded.edge_type,
                properties_json = excluded.properties_json,
                confidence = excluded.confidence,
                source_evidence_id = excluded.source_evidence_id,
                updated_at = excluded.updated_at;
            """,
            edge.to_db_row()
        )

    @check_readonly
    def upsert_evidence(self, evidence: Evidence) -> None:
        """근거 데이터를 삽입하거나 이미 존재하는 경우 덮어쓴다."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO graph_evidence (evidence_id, chunk_id, canonical_chunk_id, doc_short, doc_name, pdf_filename, page_start, page_end, source_version, source_method, table_id, row_index, row_text, metadata_json, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                chunk_id = excluded.chunk_id,
                canonical_chunk_id = excluded.canonical_chunk_id,
                doc_short = excluded.doc_short,
                doc_name = excluded.doc_name,
                pdf_filename = excluded.pdf_filename,
                page_start = excluded.page_start,
                page_end = excluded.page_end,
                source_version = excluded.source_version,
                source_method = excluded.source_method,
                table_id = excluded.table_id,
                row_index = excluded.row_index,
                row_text = excluded.row_text,
                metadata_json = excluded.metadata_json,
                confidence = excluded.confidence;
            """,
            evidence.to_db_row()
        )

    @check_readonly
    def add_alias(self, alias: Alias) -> None:
        """동의어를 데이터베이스에 삽입하거나 이미 존재하는 경우 덮어쓴다."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO graph_aliases (alias_id, node_id, alias, normalized_alias, source, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(alias_id) DO UPDATE SET
                node_id = excluded.node_id,
                alias = excluded.alias,
                normalized_alias = excluded.normalized_alias,
                source = excluded.source,
                confidence = excluded.confidence;
            """,
            alias.to_db_row()
        )

    @check_readonly
    def link_node_evidence(self, node_id: str, evidence_id: str, role: str) -> None:
        """노드와 근거 데이터를 연결한다."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO graph_node_evidence (node_id, evidence_id, role)
            VALUES (?, ?, ?)
            ON CONFLICT(node_id, evidence_id, role) DO NOTHING;
            """,
            (node_id, evidence_id, role)
        )

    @check_readonly
    def link_edge_evidence(self, edge_id: str, evidence_id: str, role: str) -> None:
        """엣지와 근거 데이터를 연결한다."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO graph_edge_evidence (edge_id, evidence_id, role)
            VALUES (?, ?, ?)
            ON CONFLICT(edge_id, evidence_id, role) DO NOTHING;
            """,
            (edge_id, evidence_id, role)
        )

    @check_readonly
    def set_manifest(self, key: str, value: str) -> None:
        """빌드 Manifest 항목을 저장한다."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO graph_build_manifest (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """,
            (key, value)
        )

    def get_manifest(self, key: str) -> str | None:
        """빌드 Manifest 값을 가져온다."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM graph_build_manifest WHERE key = ?;", (key,))
        row = cursor.fetchone()
        return row["value"] if row else None

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """일반 SQL 쿼리를 실행하여 결과를 반환한다."""
        cursor = self.conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()

    @check_readonly
    def execute(self, sql: str, params: tuple = ()) -> None:
        """일반 SQL 명령을 실행한다."""
        cursor = self.conn.cursor()
        cursor.execute(sql, params)

    @check_readonly
    def commit(self) -> None:
        """현재 트랜잭션의 변경사항을 저장한다."""
        self.conn.commit()

    @check_readonly
    def rollback(self) -> None:
        """현재 트랜잭션의 변경사항을 롤백한다."""
        self.conn.rollback()

    @check_readonly
    def begin(self) -> None:
        """명시적으로 트랜잭션을 시작한다."""
        self.conn.execute("BEGIN TRANSACTION;")


    @check_readonly
    def upsert_nodes_bulk(self, nodes: list[Node]) -> None:
        """대량의 노드를 단일 트랜잭션으로 빠르게 삽입한다."""
        cursor = self.conn.cursor()
        now_str = datetime.now().isoformat()
        rows = []
        for node in nodes:
            node.updated_at = now_str
            rows.append(node.to_db_row())

        cursor.executemany(
            """
            INSERT INTO graph_nodes (node_id, node_type, canonical_name, normalized_name, properties_json, confidence, created_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                node_type = excluded.node_type,
                canonical_name = excluded.canonical_name,
                normalized_name = excluded.normalized_name,
                properties_json = excluded.properties_json,
                confidence = excluded.confidence,
                updated_at = excluded.updated_at;
            """,
            rows
        )

    @check_readonly
    def add_aliases_bulk(self, aliases: list[Alias]) -> None:
        """대량의 동의어를 단일 트랜잭션으로 빠르게 삽입한다."""
        cursor = self.conn.cursor()
        rows = [alias.to_db_row() for alias in aliases]
        cursor.executemany(
            """
            INSERT INTO graph_aliases (alias_id, node_id, alias, normalized_alias, source, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(alias_id) DO UPDATE SET
                node_id = excluded.node_id,
                alias = excluded.alias,
                normalized_alias = excluded.normalized_alias,
                source = excluded.source,
                confidence = excluded.confidence;
            """,
            rows
        )

    @check_readonly
    def upsert_edges_bulk(self, edges: list[Edge]) -> None:
        """대량의 엣지를 단일 트랜잭션으로 빠르게 삽입한다."""
        cursor = self.conn.cursor()
        now_str = datetime.now().isoformat()
        rows = []
        for edge in edges:
            edge.updated_at = now_str
            rows.append(edge.to_db_row())
        cursor.executemany(
            """
            INSERT INTO graph_edges (edge_id, source_node_id, target_node_id, edge_type, properties_json, confidence, source_evidence_id, created_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(edge_id) DO UPDATE SET
                source_node_id = excluded.source_node_id,
                target_node_id = excluded.target_node_id,
                edge_type = excluded.edge_type,
                properties_json = excluded.properties_json,
                confidence = excluded.confidence,
                source_evidence_id = excluded.source_evidence_id,
                updated_at = excluded.updated_at;
            """,
            rows
        )

    @check_readonly
    def upsert_evidences_bulk(self, evidences: list[Evidence]) -> None:
        """대량의 근거 데이터를 단일 트랜잭션으로 빠르게 삽입한다."""
        cursor = self.conn.cursor()
        rows = [evidence.to_db_row() for evidence in evidences]
        cursor.executemany(
            """
            INSERT INTO graph_evidence (evidence_id, chunk_id, canonical_chunk_id, doc_short, doc_name, pdf_filename, page_start, page_end, source_version, source_method, table_id, row_index, row_text, metadata_json, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                chunk_id = excluded.chunk_id,
                canonical_chunk_id = excluded.canonical_chunk_id,
                doc_short = excluded.doc_short,
                doc_name = excluded.doc_name,
                pdf_filename = excluded.pdf_filename,
                page_start = excluded.page_start,
                page_end = excluded.page_end,
                source_version = excluded.source_version,
                source_method = excluded.source_method,
                table_id = excluded.table_id,
                row_index = excluded.row_index,
                row_text = excluded.row_text,
                metadata_json = excluded.metadata_json,
                confidence = excluded.confidence;
            """,
            rows
        )

    @check_readonly
    def link_node_evidences_bulk(self, links: list[tuple[str, str, str]]) -> None:
        """노드와 근거 데이터를 대량으로 연결한다."""
        cursor = self.conn.cursor()
        cursor.executemany(
            """
            INSERT INTO graph_node_evidence (node_id, evidence_id, role)
            VALUES (?, ?, ?)
            ON CONFLICT(node_id, evidence_id, role) DO NOTHING;
            """,
            links
        )

    @check_readonly
    def link_edge_evidences_bulk(self, links: list[tuple[str, str, str]]) -> None:
        """엣지와 근거 데이터를 대량으로 연결한다."""
        cursor = self.conn.cursor()
        cursor.executemany(
            """
            INSERT INTO graph_edge_evidence (edge_id, evidence_id, role)
            VALUES (?, ?, ?)
            ON CONFLICT(edge_id, evidence_id, role) DO NOTHING;
            """,
            links
        )

    @contextlib.contextmanager
    def transaction(self):
        """명시적 트랜잭션을 시작하고 예외 발생 시 롤백하는 Context Manager."""
        if self.readonly:
            raise PermissionError("Cannot start a transaction in read-only mode.")
        self.begin()
        try:
            yield
            self.commit()
        except Exception:
            self.rollback()
            raise

    def close(self) -> None:
        """데이터베이스 연결을 닫는다."""
        self.conn.close()
