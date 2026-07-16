import pytest
import sqlite3
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.db import Base
from src.api.models import AuditLog, ChatMessage, ChatSession
from src.api.routes import admin
from src.auth.users import User
from tests.test_check_graph_vector_sync import FakeCollection


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session

    await engine.dispose()


def _admin_user() -> User:
    return User(
        username="admin",
        password_hash="hash",
        role="admin",
        display_name="관리자",
        created_at="2026-05-20T00:00:00+00:00",
        password_updated_at="2026-05-20T00:00:00+00:00",
    )


@pytest.mark.anyio
async def test_admin_stats_returns_live_aggregates(db_session) -> None:
    session = ChatSession(id="sess-1", user_id="admin", title="테스트")
    db_session.add(session)
    db_session.add(ChatMessage(session_id="sess-1", role="assistant", content="답변", sources=[]))
    db_session.add(
        AuditLog(
            user_id="admin",
            event_type="CHAT_QUERY",
            detail={
                "mode": "general",
                "model": "sglang:gpt-oss-20b",
                "elapsed_ms": 1234,
                "source_count": 4,
                "query_preview": "도수치료 보상돼?",
                "rag_diagnostics": {
                    "warnings": [{"code": "CLARIFICATION_RECOMMENDED", "message": "확인 질문 권장"}],
                    "ambiguous_terms": ["실손 세대"],
                    "clarification_questions": ["어느 실손 세대 기준인지 확인해 주세요."],
                },
            },
        )
    )
    db_session.add(
        AuditLog(
            user_id="admin",
            event_type="CHAT_QUERY_FAILED",
            detail={
                "mode": "general",
                "model": "ollama:exaone3.5:7.8b",
                "query_preview": "실패 질의",
                "error_code": "CHAT_STREAM_FAILED",
                "error_message": "LLM 호출 실패",
            },
        )
    )
    db_session.add(
        AuditLog(
            user_id="admin",
            event_type="CHAT_QUERY",
            detail={
                "mode": "general",
                "model": "ollama:exaone3.5:7.8b",
                "elapsed_ms": 2468,
                "source_count": 0,
                "query_preview": "근거 없는 질의",
            },
        )
    )
    await db_session.commit()

    payload = await admin.stats(_admin_user(), db_session)

    assert payload["total_queries"] == 2
    assert payload["total_answers"] == 1
    assert payload["avg_elapsed_sec"] == 1.85
    assert payload["avg_source_count"] == 2
    assert payload["mode_distribution"]["general"] == 2
    assert payload["user_distribution"]["admin"] == 2
    assert payload["model_distribution"]["sglang:gpt-oss-20b"] == 1
    assert payload["model_distribution"]["ollama:exaone3.5:7.8b"] == 1
    quality_by_model = {item["model"]: item for item in payload["model_quality_stats"]}
    assert quality_by_model["sglang:gpt-oss-20b"]["error_rate"] == 0
    assert quality_by_model["sglang:gpt-oss-20b"]["avg_elapsed_sec"] == 1.23
    assert quality_by_model["sglang:gpt-oss-20b"]["citation_missing_rate"] == 0
    assert quality_by_model["ollama:exaone3.5:7.8b"]["total_attempts"] == 2
    assert quality_by_model["ollama:exaone3.5:7.8b"]["failure_count"] == 1
    assert quality_by_model["ollama:exaone3.5:7.8b"]["error_rate"] == 0.5
    assert quality_by_model["ollama:exaone3.5:7.8b"]["avg_elapsed_sec"] == 2.47
    assert quality_by_model["ollama:exaone3.5:7.8b"]["citation_missing_rate"] == 1
    assert payload["issue_stats"]["failed_query_count"] == 1
    assert payload["issue_stats"]["warning_query_count"] == 1
    assert payload["issue_stats"]["total_warning_count"] == 1
    assert payload["issue_stats"]["ambiguity_query_count"] == 1
    assert payload["issue_stats"]["clarification_question_count"] == 1
    assert payload["issue_stats"]["warning_code_distribution"]["CLARIFICATION_RECOMMENDED"] == 1
    assert payload["issue_stats"]["ambiguous_term_distribution"]["실손 세대"] == 1
    assert payload["issue_stats"]["recent_failures"][0]["error_code"] == "CHAT_STREAM_FAILED"
    assert payload["issue_stats"]["recent_warnings"][0]["query_preview"] == "도수치료 보상돼?"
    assert payload["issue_stats"]["recent_ambiguities"][0]["ambiguous_terms"] == ["실손 세대"]


@pytest.mark.anyio
async def test_system_summary_reports_only_running_llm_models(monkeypatch) -> None:
    monkeypatch.setattr(
        admin,
        "list_runtime_available_models",
        lambda: {
            "sglang": ["qwen3-next-80b-a3b-instruct-fp8"],
            "vllm": [],
            "trtllm": [],
            "ollama": [],
            "openai": [],
        },
    )

    payload = await admin.system_summary(_admin_user())

    assert payload["llm"]["running_models"]["sglang"] == ["qwen3-next-80b-a3b-instruct-fp8"]
    assert "available_models" not in payload["llm"]
    assert "default_local_model" not in payload["llm"]


@pytest.mark.anyio
async def test_latest_rag_diagnostics_returns_latest_general_query(db_session) -> None:
    db_session.add(
        AuditLog(
            user_id="admin",
            event_type="CHAT_QUERY",
            detail={
                "mode": "general",
                "rag_diagnostics": {
                    "query_preview": "도수치료 보상돼?",
                    "model": "sglang:gpt-oss-20b",
                    "index_mode": "default",
                    "effective_index_mode": "default",
                    "warnings": [],
                    "normalized_terms": {"영수증만": "증빙 부족"},
                    "term_correction_candidates": [
                        {
                            "raw": "엠알아이",
                            "normalized": "MRI",
                            "confidence": 0.72,
                            "source": "safe_candidate_rule",
                            "reason": "확인 필요",
                        }
                    ],
                    "ambiguous_terms": ["실손 세대"],
                    "clarification_questions": ["어느 실손 세대 기준인지 확인해 주세요."],
                    "graph_review_path_count": 1,
                    "steps": [
                        {
                            "key": "bm25",
                            "label": "BM25 키워드 검색",
                            "result": "5건",
                            "elapsed_ms": None,
                            "status": "done",
                        }
                    ],
                },
            },
        )
    )
    await db_session.commit()

    payload = await admin.latest_rag_diagnostics(_admin_user(), db_session)

    assert payload["available"] is True
    assert payload["query_preview"] == "도수치료 보상돼?"
    assert payload["normalized_terms"] == {"영수증만": "증빙 부족"}
    assert payload["term_correction_candidates"][0]["raw"] == "엠알아이"
    assert payload["ambiguous_terms"] == ["실손 세대"]
    assert payload["clarification_questions"] == ["어느 실손 세대 기준인지 확인해 주세요."]
    assert payload["graph_review_path_count"] == 1
    assert payload["steps"][0]["label"] == "BM25 키워드 검색"


@pytest.mark.anyio
async def test_graph_vector_sync_returns_sampled_summary(tmp_path, monkeypatch) -> None:
    graph_path = tmp_path / "insurance_graph.sqlite"
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    (chroma_dir / "chroma.sqlite3").write_text("", encoding="utf-8")
    with sqlite3.connect(graph_path) as conn:
        conn.execute(
            """
            CREATE TABLE graph_evidence (
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
            )
            """
        )
        conn.executemany(
            "INSERT INTO graph_evidence (evidence_id, chunk_id, canonical_chunk_id, doc_short, page_start, page_end, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("ev_direct", "direct_ch_001", None, "약관", 1, 1, "{}"),
                ("ev_source", "graph_only_001", None, "약관", 5, 5, '{"source_chunk_id":"legacy_source_001"}'),
                ("ev_page", "약관_missing_ch_999999", None, "약관", 10, 10, "{}"),
                ("ev_missing", "missing_ch_001", None, "없는문서", 1, 1, "{}"),
            ],
        )

    class FakeVectorStore:
        def __init__(self, _chroma_dir):
            self.collection = FakeCollection()

    monkeypatch.setattr(admin.config, "GRAPH_INDEX_PATH", graph_path)
    captured = {}

    def fake_resolve_index_paths(mode):
        captured["index_mode"] = mode
        return tmp_path / "bm25.pkl", chroma_dir

    monkeypatch.setattr(admin, "resolve_index_paths", fake_resolve_index_paths)
    monkeypatch.setattr(admin, "VectorStore", FakeVectorStore)

    payload = await admin.graph_vector_sync("default", 10, 20260531, _admin_user())

    assert payload["available"] is True
    assert payload["index_mode"] == "v2_only"
    assert captured["index_mode"] == "v2_only"
    assert payload["sampled_evidence_rows"] == 4
    assert payload["summary"]["status_counts"]["direct_hit"] == 1
    assert payload["summary"]["status_counts"]["source_chunk_hit"] == 1
    assert payload["summary"]["status_counts"]["doc_page_hit"] == 1
    assert payload["summary"]["status_counts"]["missing"] == 1


@pytest.mark.anyio
async def test_graph_sync_status_returns_build_manifest(tmp_path, monkeypatch) -> None:
    graph_path = tmp_path / "insurance_graph.sqlite"
    manifest_path = tmp_path / "insurance_graph_manifest.json"
    with sqlite3.connect(graph_path) as conn:
        conn.execute("CREATE TABLE graph_nodes (node_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE graph_edges (edge_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE graph_evidence (evidence_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE graph_aliases (alias_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE graph_node_evidence (node_id TEXT, evidence_id TEXT, role TEXT)")
        conn.execute("CREATE TABLE graph_edge_evidence (edge_id TEXT, evidence_id TEXT, role TEXT)")
        conn.execute("CREATE TABLE graph_build_manifest (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany("INSERT INTO graph_nodes (node_id) VALUES (?)", [("n1",), ("n2",)])
        conn.execute("INSERT INTO graph_edges (edge_id) VALUES ('e1')")
        conn.execute("INSERT INTO graph_evidence (evidence_id) VALUES ('ev1')")
        conn.executemany(
            "INSERT INTO graph_build_manifest (key, value) VALUES (?, ?)",
            [
                ("build_date", "2026-06-01T11:02:13"),
                ("source_mode", "v1_v2_combined"),
                ("node_count", "2"),
            ],
        )
    manifest_path.write_text(
        '{"build_date":"2026-06-01T11:02:13","source_mode":"v1_v2_combined","node_count":2,"edge_count":1,"evidence_count":1}',
        encoding="utf-8",
    )
    monkeypatch.setattr(admin.config, "GRAPH_INDEX_PATH", graph_path)

    payload = await admin.graph_sync_status(_admin_user())

    assert payload["available"] is True
    assert payload["status"] == "success"
    assert payload["pipeline_success"] is True
    assert payload["sync_target"] == "sqlite_property_graph"
    assert payload["manifest_exists"] is True
    assert payload["build_date"] == "2026-06-01T11:02:13"
    assert payload["source_mode"] == "v1_v2_combined"
    assert payload["loaded_rows"]["nodes"] == 2
    assert payload["loaded_rows"]["edges"] == 1
    assert payload["loaded_rows"]["evidence"] == 1
    assert payload["operation_summary"]["nodes_loaded"] == 2
    assert payload["operation_summary"]["edges_loaded"] == 1
    assert payload["operation_summary"]["technical_error_count"] == 0
    assert payload["operation_summary"]["network_error_applicable"] is False
