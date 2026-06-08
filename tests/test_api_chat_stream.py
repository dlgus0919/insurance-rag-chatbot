import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.db import Base
from src.api.models import AuditLog, ChatMessage, ChatSession
from src.api.rag_service import prepare_retrieved_context
from src.api.routes import chat, sessions
from src.api.schemas.chat import ChatRequest
from src.api.schemas.sessions import SessionCreateRequest
from src.auth.users import User
from src.graph.query_planner import GraphQueryPlan
from src.graph.retriever import GraphEvidence, GraphFact, GraphRetrievalResult


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")

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


class FakeLLM:
    def __init__(self):
        self.closed = False

    def generate_stream(self, prompt, system="", temperature=0.2):
        yield "실손 "
        yield "답변"


class ReasoningFakeLLM:
    def __init__(self):
        self.reasoning_modes: list[str] = []
        self.last_safety_warnings = [
            {"code": "THINKING_ONLY_OUTPUT", "message": "모델이 내부 추론만 반환했습니다."}
        ]
        self.last_reasoning_supported = True
        self.last_reasoning_filtered = True
        self.last_finish_reason = "length"
        self.last_final_retry_finish_reason = "stop"

    def generate_stream(self, prompt, system="", temperature=0.2, reasoning_mode="off"):
        self.reasoning_modes.append(reasoning_mode)
        yield "fallback 답변"


class StructuredTemplateLLM:
    def generate_stream(self, prompt, system="", temperature=0.2):
        yield "N39.3은 보상 제외로 판단됩니다.\n\n"
        yield "■ 섹션 1️⃣ 【확정 근거】\n해당 없음\n"
        yield "■ 섹션 2️⃣ 【검토 필요 사항】\n질병/상해 구분 확인\n"


class FakePipeline:
    def __init__(self):
        self.llm = FakeLLM()
        self.graph_enabled = False
        self.graph_retriever = None
        self.last_doc_filter = None

    def retrieve_hits(self, question, top_k=None, doc_filter=None, return_debug=False, graph_hits=None):
        self.last_doc_filter = doc_filter
        hits = [
            type(
                "Hit",
                (),
                {
                    "id": "chunk-1",
                    "document": "도수치료 약관 내용",
                    "metadata": {
                        "pdf_filename": "약관.pdf",
                        "doc_short": "약관",
                        "page_start": 14,
                        "page_end": 14,
                    },
                    "score": 0.91,
                },
            )()
        ]
        debug = None
        if return_debug:
            debug = chat.DebugInfo(
                dense_hits=[],
                bm25_hits=[],
                rrf_hits=[],
                final_hits=[],
            )
        return (hits, debug)

    def build_prompt(self, question, chunks, graph_context=None):
        return f"질문: {question}\n근거 수: {len(chunks)}"


class FakeGraphRetriever:
    def retrieve(self, question):
        return GraphRetrievalResult(
            plan=GraphQueryPlan(
                intents=["surgery_grade_lookup"],
                procedure_name="기관지 식도루 폐쇄술",
                grade_system="신1-5종",
            ),
            facts=[
                GraphFact(
                    subject="기관지 식도루 폐쇄술",
                    relation="HAS_GRADE",
                    object="신1-5종 4종",
                    confidence=1.0,
                    status="confirmed",
                    evidence=[
                        GraphEvidence(
                            evidence_id="ev-1",
                            chunk_id="missing-graph-chunk",
                            doc_short="실무가이드",
                            page_start=80,
                        )
                    ],
                )
            ],
            source_chunk_ids=["missing-graph-chunk"],
        )


class FakeVectorStore:
    def get_by_ids(self, ids):
        return []


class FakeGraphPipeline(FakePipeline):
    def __init__(self):
        super().__init__()
        self.graph_enabled = True
        self.graph_retriever = FakeGraphRetriever()
        self.vector_store = FakeVectorStore()


class ReasoningFakePipeline(FakePipeline):
    def __init__(self):
        super().__init__()
        self.llm = ReasoningFakeLLM()


class StructuredTemplatePipeline(FakePipeline):
    def __init__(self):
        super().__init__()
        self.llm = StructuredTemplateLLM()


def _user(username: str = "employee01") -> User:
    return User(
        username=username,
        password_hash="hash",
        role="employee",
        display_name=username,
        created_at="2026-05-20T00:00:00+00:00",
        password_updated_at="2026-05-20T00:00:00+00:00",
    )


@pytest.mark.anyio
async def test_chat_stream_uses_rag_sse_and_persists_messages(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k: FakePipeline())
    created = await sessions.create_session(SessionCreateRequest(title="도수치료"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(query="도수치료 보상돼?", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert response.media_type == "text/event-stream"
    assert stream.index("event: status") < stream.index("event: sources") < stream.index("event: token")
    assert "event: done" in stream
    assert messages[0].role == "user"
    assert messages[0].content == "도수치료 보상돼?"
    assert messages[1].role == "assistant"
    assert "실손 답변" in messages[1].content
    assert messages[1].sources[0]["filename"] == "약관.pdf"
    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.event_type == "CHAT_QUERY"))
    audit_entry = audit_result.scalar_one()
    assert audit_entry.detail["model"] == "gemma3:4b"
    assert audit_entry.detail["reasoning_mode"] == "off"
    assert audit_entry.detail["reasoning_supported"] is False
    assert audit_entry.detail["reasoning_filtered"] is False
    assert audit_entry.detail["rag_diagnostics"]["steps"][-1]["label"] == "LLM 답변 생성"


@pytest.mark.anyio
async def test_chat_stream_passes_reasoning_mode_and_records_audit(db_session, monkeypatch) -> None:
    pipeline = ReasoningFakePipeline()
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k: pipeline)
    created = await sessions.create_session(SessionCreateRequest(title="Qwen"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(
            query="Qwen 추론 모드 테스트",
            session_id=created.id,
            model="sglang:qwen3-next-80b-a3b-thinking-fp8",
            reasoning_mode="on",
        ),
        None,
        _user(),
        db_session,
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.event_type == "CHAT_QUERY"))
    audit_entry = audit_result.scalar_one()

    assert pipeline.llm.reasoning_modes == ["on"]
    assert "event: warning" in stream
    assert "THINKING_ONLY_OUTPUT" in stream
    assert audit_entry.detail["model"] == "sglang:qwen3-next-80b-a3b-thinking-fp8"
    assert audit_entry.detail["reasoning_mode"] == "on"
    assert audit_entry.detail["reasoning_supported"] is True
    assert audit_entry.detail["reasoning_filtered"] is True
    assert audit_entry.detail["finish_reason"] == "length"
    assert audit_entry.detail["final_retry_finish_reason"] == "stop"
    assert "THINKING_ONLY_OUTPUT" in audit_entry.detail["warning_codes"]


@pytest.mark.anyio
async def test_chat_stream_preserves_model_structured_template_when_graph_payload_is_empty(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k: StructuredTemplatePipeline())

    async def fake_prepare(*_args, **_kwargs):
        return [], [], "prompt", {"graph_review_paths": [], "facts": [], "plan": {}}, [], None, None

    monkeypatch.setattr(chat, "prepare_retrieved_context", fake_prepare)
    created = await sessions.create_session(SessionCreateRequest(title="빈 그래프"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(query="N39.3 보상 가능 여부", session_id=created.id, model="ollama:llama-3.3-70b-instruct-q4-k-m"),
        None,
        _user(),
        db_session,
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert "event: graph" in stream
    assert "■ 섹션 1️⃣" in stream
    assert "【확정 근거】" in messages[1].content


@pytest.mark.anyio
async def test_chat_stream_strips_model_structured_template_when_graph_payload_is_renderable(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k: StructuredTemplatePipeline())

    async def fake_prepare(*_args, **_kwargs):
        return (
            [],
            [],
            "prompt",
            {
                "graph_review_paths": [
                    {
                        "path_type": "diagnosis_review",
                        "path_type_label": "진단코드 검토",
                        "status": "confirmed",
                        "status_label": "확정",
                    }
                ],
                "facts": [],
                "plan": {},
            },
            [],
            None,
            None,
        )

    monkeypatch.setattr(chat, "prepare_retrieved_context", fake_prepare)
    created = await sessions.create_session(SessionCreateRequest(title="그래프 패널"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(query="N39.3 보상 가능 여부", session_id=created.id, model="ollama:llama-3.3-70b-instruct-q4-k-m"),
        None,
        _user(),
        db_session,
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert "event: graph" in stream
    assert "진단코드 검토" in stream
    assert messages[1].content == "N39.3은 보상 제외로 판단됩니다."
    assert "■ 섹션" not in messages[1].content


@pytest.mark.anyio
async def test_formal_chat_stream_records_search_type_in_audit_log(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k: FakePipeline())
    created = await sessions.create_session(SessionCreateRequest(title="약관정형"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(
            query="N39.3",
            session_id=created.id,
            mode="formal",
            filters={"search_type": "약관 조문 검색"},
            model="gemma3:4b",
        ),
        None,
        _user(),
        db_session,
    )
    async for _chunk in response.body_iterator:
        pass

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.event_type == "CHAT_QUERY"))
    audit_entries = list(audit_result.scalars())
    formal_entry = audit_entries[-1]

    assert formal_entry.detail["mode"] == "formal"
    assert formal_entry.detail["search_type"] == "약관 조문 검색"


@pytest.mark.anyio
async def test_persist_turn_stores_graph_payload_for_history_restore(db_session) -> None:
    created = await sessions.create_session(SessionCreateRequest(title="진단코드"), _user(), db_session)

    await chat._persist_turn(
        db_session,
        created.id,
        "기관지 식도루 폐쇄술의 신1-5종 수술 종수는?",
        "답변",
        [{"filename": "약관.pdf", "page": 14}],
        graph_payload={"source_chunk_ids": ["missing-graph-chunk"], "graph_review_paths": []},
        warnings=[{"code": "GRAPH_MISSING", "message": "missing"}],
    )

    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert messages[1].sources
    meta_source = messages[1].sources[-1]
    assert meta_source["__kind"] == "assistant_meta"
    assert meta_source["graph_result"]["source_chunk_ids"] == ["missing-graph-chunk"]
    assert meta_source["warnings"][0]["code"] == "GRAPH_MISSING"


@pytest.mark.anyio
async def test_chat_stream_recovers_from_stale_session_id(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k: FakePipeline())

    response = await chat.chat_stream(
        ChatRequest(query="기관지 식도루 폐쇄술 종수는?", session_id="stale-session", model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    session_result = await db_session.execute(select(ChatSession))
    created_sessions = list(session_result.scalars())
    message_result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created_sessions[0].id).order_by(ChatMessage.id.asc())
    )
    messages = list(message_result.scalars())

    assert "event: error" not in stream
    assert "event: done" in stream
    assert len(created_sessions) == 1
    assert created_sessions[0].title == "기관지 식도루 폐쇄술 종수는?"
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


@pytest.mark.anyio
async def test_session_export_filters_internal_assistant_meta_sources(db_session) -> None:
    created = await sessions.create_session(SessionCreateRequest(title="내보내기"), _user(), db_session)
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="답변",
            sources=[
                {"filename": "약관.pdf", "page": 12},
                {
                    "__kind": "assistant_meta",
                    "graph_result": {
                        "graph_review_paths": [
                            {
                                "path_type": "diagnosis_review",
                                "path_type_label": "진단코드 검토",
                                "status": "confirmed",
                                "status_label": "확정",
                                "summary": "문서에 직접 언급된 진단코드 근거 확인",
                                "review_actions": ["질병/상해 구분 확인"],
                                "exclusion_reasons": ["약관상 보상제외 치료"],
                            }
                        ]
                    },
                    "warnings": [{"code": "CLARIFICATION_RECOMMENDED", "message": "추가 확인 질문 권장"}],
                },
            ],
        )
    )
    await db_session.commit()

    response = await sessions.export_session(None, created.id, "json", _user(), db_session)
    body = response.body.decode("utf-8") if isinstance(response.body, bytes) else response.body

    assert "assistant_meta" not in body
    assert "약관.pdf" in body
    assert "진단코드 검토" in body
    assert "질병/상해 구분 확인" in body
    assert "CLARIFICATION_RECOMMENDED" in body


@pytest.mark.anyio
async def test_list_messages_and_export_preserve_embedded_review_template_without_graph_panel(db_session) -> None:
    created = await sessions.create_session(SessionCreateRequest(title="복원"), _user(), db_session)
    raw_template = (
        "■ 섹션 1️⃣  【확정 근거】\n"
        "해당 없음\n\n"
        "■ 섹션 2️⃣  【검토 필요 사항】\n"
        "- 합병증 특약 가입 여부 확인이 필요합니다.\n"
        "  ⚠️ 이유: Graph review path가 자동 확정이 아닌 검토 대상으로 반환되었습니다.\n"
    )
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content=raw_template,
            sources=[
                {
                    "__kind": "assistant_meta",
                    "graph_result": {"graph_review_paths": [], "facts": [], "plan": {}},
                    "warnings": [],
                }
            ],
        )
    )
    await db_session.commit()

    messages = await sessions.list_messages(created.id, _user(), db_session)
    response = await sessions.export_session(None, created.id, "txt", _user(), db_session)
    body = response.body.decode("utf-8") if isinstance(response.body, bytes) else response.body

    assert "■ 섹션" in messages[0].content
    assert "합병증 특약 가입 여부 확인이 필요합니다." in messages[0].content
    assert "■ 섹션" in body
    assert "합병증 특약 가입 여부 확인이 필요합니다." in body


@pytest.mark.anyio
async def test_list_messages_and_export_sanitize_embedded_review_template_with_graph_panel(db_session) -> None:
    created = await sessions.create_session(SessionCreateRequest(title="복원"), _user(), db_session)
    raw_template = (
        "N39.3은 보상 제외로 판단됩니다.\n\n"
        "■ 섹션 1️⃣  【확정 근거】\n"
        "해당 없음\n\n"
        "■ 섹션 2️⃣  【검토 필요 사항】\n"
        "- 질병/상해 구분 확인\n"
    )
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content=raw_template,
            sources=[
                {
                    "__kind": "assistant_meta",
                    "graph_result": {
                        "graph_review_paths": [
                            {
                                "path_type": "diagnosis_review",
                                "path_type_label": "진단코드 검토",
                                "status": "confirmed",
                                "status_label": "확정",
                                "summary": "문서에 직접 언급된 진단코드 근거 확인",
                            }
                        ]
                    },
                    "warnings": [],
                }
            ],
        )
    )
    await db_session.commit()

    messages = await sessions.list_messages(created.id, _user(), db_session)
    response = await sessions.export_session(None, created.id, "txt", _user(), db_session)
    body = response.body.decode("utf-8") if isinstance(response.body, bytes) else response.body

    assert messages[0].content == "N39.3은 보상 제외로 판단됩니다."
    assert "■ 섹션" not in body
    assert "진단코드 검토" in body


@pytest.mark.anyio
async def test_list_messages_and_export_strip_trailing_source_citations(db_session) -> None:
    created = await sessions.create_session(SessionCreateRequest(title="출처정리"), _user(), db_session)
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content=(
                "N39.3 진단코드는 보상 제외입니다.\n\n"
                "[출처: 약관, 제3조(보장종목별 보상내용), p.38]\n"
                "[출처: 표준약관, 제4조(보상하지 않는 사항), p.268-279]"
            ),
            sources=[
                {"filename": "약관.pdf", "page": 38},
                {"filename": "표준약관.pdf", "page": 268},
            ],
        )
    )
    await db_session.commit()

    messages = await sessions.list_messages(created.id, _user(), db_session)
    response = await sessions.export_session(None, created.id, "txt", _user(), db_session)
    body = response.body.decode("utf-8") if isinstance(response.body, bytes) else response.body

    assert messages[0].content == "N39.3 진단코드는 보상 제외입니다."
    assert "[출처:" not in body
    assert "출처: 약관.pdf (p.38); 표준약관.pdf (p.268)" in body


@pytest.mark.anyio
async def test_prepare_retrieved_context_hides_missing_graph_chunk_warning() -> None:
    _chunks, _sources, _prompt, graph_payload, warnings, _deterministic_answer, debug = await prepare_retrieved_context(
        FakeGraphPipeline(),
        "기관지 식도루 폐쇄술의 신1-5종 수술 종수는?",
        8,
        [],
    )

    assert graph_payload["source_chunk_ids"] == ["missing-graph-chunk"]
    assert warnings == []
    assert debug is not None


@pytest.mark.anyio
async def test_prepare_retrieved_context_applies_requested_doc_filter() -> None:
    pipeline = FakePipeline()

    _chunks, _sources, _prompt, _graph_payload, _warnings, _deterministic_answer, _debug = await prepare_retrieved_context(
        pipeline,
        "도수치료 보상 기준 알려줘",
        6,
        [],
        {"doc_filter": ["약관", "표준약관"]},
    )

    assert pipeline.last_doc_filter == ["약관", "표준약관"]



def test_rag_diagnostics_include_clarification_and_normalized_terms() -> None:
    debug = chat.DebugInfo(dense_hits=[], bm25_hits=[], rrf_hits=[], final_hits=[])
    debug.graph_result = GraphRetrievalResult(
        plan=GraphQueryPlan(
            intents=['session_claim_path_review'],
            normalized_terms={'영수증만': '증빙 부족'},
            term_correction_candidates=[{'raw': '엠알아이', 'normalized': 'MRI', 'confidence': 0.72}],
            ambiguous_terms=['실손 세대'],
            clarification_questions=['어느 실손 세대 기준인지 확인해 주세요.'],
        ),
        review_paths=[object()],
    )

    payload = chat._build_rag_diagnostics(
        question='영수증만 있는 도수치료 청구를 계산해도 되나요?',
        model='sglang:gpt-oss-20b',
        index_mode='default',
        effective_index_mode='default',
        debug=debug,
        source_count=1,
        warnings=[],
        elapsed_ms=123.4,
    )

    assert payload['normalized_terms'] == {'영수증만': '증빙 부족'}
    assert payload['term_correction_candidates'][0]['raw'] == '엠알아이'
    assert payload['ambiguous_terms'] == ['실손 세대']
    assert payload['clarification_questions'] == ['어느 실손 세대 기준인지 확인해 주세요.']
    assert payload['graph_review_path_count'] == 1
