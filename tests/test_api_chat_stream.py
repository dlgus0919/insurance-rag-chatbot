import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.db import Base
from src.api.models import AuditLog, ChatMessage, ChatSession
from src.api.rag_service import prepare_retrieved_context
from src.api.routes import chat, sessions
from src.api.routes.claim import _claim_snapshot_context
from src.api.routes.chat import _document_filter_options, _select_model as select_chat_model
from src.api.schemas.claim import ClaimCaseContextRequest
from src.api.schemas.chat import ChatRequest
from src.api.schemas.sessions import SessionCreateRequest
from src.auth.users import User
from src.graph.query_planner import GraphQueryPlan
from src.graph.retriever import GraphEvidence, GraphFact, GraphRetrievalResult, GraphRetriever


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
        self.last_retrieval_question = question
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


async def _stream_text(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def _claim_snapshot_source_for_chat(
    *,
    claim_id: str = "claim-1",
    payable_amount: str = "105000",
    line_results: list[dict] | None = None,
    input_items: list[dict] | None = None,
) -> dict:
    return {
        "__kind": "assistant_meta",
        "claim_snapshot": {
            "schema_version": 1,
            "claim_id": claim_id,
            "input": {
                "items": input_items
                or [
                    {
                        "line_id": "line-1",
                        "input_name": "도수치료",
                        "claimed_amount": "150000",
                        "insured_copay_amount": "0",
                        "nonpay_amount": "150000",
                        "quantity": "1",
                        "user_category_hint": "3대비급여",
                    },
                    {
                        "line_id": "line-2",
                        "input_name": "비타민D 주사",
                        "claimed_amount": "48000",
                        "insured_copay_amount": "0",
                        "nonpay_amount": "48000",
                        "quantity": "1",
                        "user_category_hint": "",
                    },
                ],
                "context": {"policy_generation": "4th", "visit_type": "outpatient", "coverage_topic": "실손"},
            },
            "result": {
                "payable_amount": payable_amount,
                "deductible": "45000",
                "line_results": line_results
                or [
                    {
                        "line_id": "line-1",
                        "input_name": "도수치료",
                        "category": "3대비급여",
                        "claimed_amount": "150000",
                        "deductible": "45000",
                        "payable_amount": "105000",
                        "calculation_status": "calculated",
                        "human_task_amount": "0",
                    },
                    {
                        "line_id": "line-2",
                        "input_name": "비타민D 주사",
                        "category": "미분류 비급여",
                        "claimed_amount": "48000",
                        "deductible": "0",
                        "payable_amount": "0",
                        "calculation_status": "human_task",
                        "human_task_amount": "48000",
                        "review_reasons": ["급여/비급여 구분 확인 필요"],
                    },
                ],
                "review_reasons": ["급여/비급여 구분 확인 필요"],
            },
        },
    }


def test_claim_case_context_request_accepts_special_calculation_status() -> None:
    payload = ClaimCaseContextRequest(
        policy_generation="5th",
        visit_type="outpatient",
        special_calculation_status="applied",
    )

    assert payload.special_calculation_status == "applied"


def test_claim_snapshot_context_keeps_special_calculation_status() -> None:
    context = ClaimCaseContextRequest(
        policy_generation="5th",
        visit_type="hospitalization",
        special_calculation_status="not_applied",
    )

    snapshot_context = _claim_snapshot_context(context)

    assert snapshot_context["special_calculation_status"] == "not_applied"


def test_recalculation_needs_special_status_for_fifth_generation_three_major() -> None:
    from src.claim_calculation.thread_recalculation import (
        detect_recalculation_intent,
        find_target_line,
        needs_special_calculation_clarification,
    )

    snapshot = _claim_snapshot_source_for_chat()
    claim_snapshot = snapshot["claim_snapshot"]
    claim_snapshot["input"]["context"] = {
        "policy_generation": "5th",
        "visit_type": "outpatient",
        "coverage_topic": "실손",
        "special_calculation_status": "unknown",
    }
    claim_snapshot["result"]["policy_generation"] = "5th"
    claim_snapshot["result"]["special_calculation_status"] = "unknown"
    query = "도수치료를 3대비급여로 보상한다면 다시 계산해줘"
    intent = detect_recalculation_intent(query)
    target_line = find_target_line(claim_snapshot, "도수치료")

    assert intent is not None
    assert target_line is not None
    assert needs_special_calculation_clarification(claim_snapshot, intent, target_line)


def test_recalculation_needs_special_status_for_generic_fifth_generation_three_major() -> None:
    from src.claim_calculation.thread_recalculation import (
        detect_recalculation_intent,
        find_target_line,
        needs_special_calculation_clarification,
    )

    snapshot = _claim_snapshot_source_for_chat(
        line_results=[
            {
                "line_id": "line-1",
                "input_name": "비타민D 검사",
                "category": "미분류 비급여",
                "claimed_amount": "20000",
            }
        ]
    )
    claim_snapshot = snapshot["claim_snapshot"]
    claim_snapshot["input"]["context"] = {
        "policy_generation": "5th",
        "visit_type": "outpatient",
        "coverage_topic": "실손",
        "special_calculation_status": "unknown",
    }
    claim_snapshot["result"]["policy_generation"] = "5th"
    claim_snapshot["result"]["special_calculation_status"] = "unknown"
    query = "비타민D 검사를 3대비급여로 보상한다면 다시 계산해줘"
    intent = detect_recalculation_intent(query)
    target_line = find_target_line(claim_snapshot, "비타민D 검사")

    assert intent is not None
    assert target_line is not None
    assert needs_special_calculation_clarification(claim_snapshot, intent, target_line)


def test_document_filter_options_include_configured_documents() -> None:
    docs = _document_filter_options()
    doc_shorts = [doc["doc_short"] for doc in docs]

    assert "약관" in doc_shorts
    assert "상담사례집" in doc_shorts
    assert "비급여 표준모델" in doc_shorts


def test_chat_default_model_uses_answer_primary_sglang(monkeypatch) -> None:
    monkeypatch.setattr(chat.config, "SGLANG_DEFAULT_MODEL", "qwen3-next-80b-a3b-instruct-fp8")

    selected = select_chat_model(ChatRequest(query="기본 모델 테스트"))

    assert selected == "sglang:qwen3-next-80b-a3b-instruct-fp8"


def test_policy_generation_context_is_added_to_general_prompt() -> None:
    query = chat._query_with_policy_generation("도수치료 보상돼?", "5th")
    prompt = chat._prompt_with_policy_generation("본문", "5th")

    assert query.startswith("[선택된 실손 세대 기준: 5세대 실손]")
    assert "사용자가 선택한 실손 세대는 5세대 실손" in prompt


@pytest.mark.anyio
async def test_general_chat_forwards_selected_policy_generation_to_retrieval(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": FakePipeline())
    captured: dict[str, object] = {}

    async def fake_prepare(*_args, **kwargs):
        captured["policy_generation"] = kwargs.get("policy_generation")
        return [], [], "prompt", {"graph_review_paths": [], "facts": [], "plan": {}}, [], "세대별 근거 답변", None

    monkeypatch.setattr(chat, "prepare_retrieved_context", fake_prepare)
    created = await sessions.create_session(SessionCreateRequest(title="세대 필터"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(
            query="노화현상으로 인한 탈모는 보상 가능한가요?",
            session_id=created.id,
            model="gemma3:4b",
            policy_generation="4th",
        ),
        None,
        _user(),
        db_session,
    )
    await _stream_text(response)

    assert captured["policy_generation"] == "4th"


@pytest.mark.anyio
async def test_general_chat_uses_current_policy_generation_for_each_turn_in_same_session(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": FakePipeline())
    captured: list[str | None] = []

    async def fake_prepare(*_args, **kwargs):
        captured.append(kwargs.get("policy_generation"))
        return [], [], "prompt", {"graph_review_paths": [], "facts": [], "plan": {}}, [], "세대별 근거 답변", None

    monkeypatch.setattr(chat, "prepare_retrieved_context", fake_prepare)
    created = await sessions.create_session(SessionCreateRequest(title="세대 전환"), _user(), db_session)

    for policy_generation in ("4th", "5th"):
        response = await chat.chat_stream(
            ChatRequest(
                query="노화현상으로 인한 탈모는 보상 가능한가요?",
                session_id=created.id,
                model="gemma3:4b",
                policy_generation=policy_generation,
            ),
            None,
            _user(),
            db_session,
        )
        await _stream_text(response)

    assert captured == ["4th", "5th"]


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


class FailingGraphRetriever(GraphRetriever):
    def __init__(self):
        super().__init__("non_existent_db_12345.sqlite")

    def retrieve(self, question):
        raise RuntimeError("graph lookup boom")


class FailingGraphPipeline(FakePipeline):
    def __init__(self):
        super().__init__()
        self.graph_enabled = True
        self.graph_retriever = FailingGraphRetriever()
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
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": FakePipeline())
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
    assert '"persisted": true' in stream
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
    assert audit_entry.detail["index_mode"] == "v2_only"
    assert audit_entry.detail["effective_index_mode"] == "v2_only"
    assert audit_entry.detail["rag_diagnostics"]["steps"][-1]["label"] == "LLM 답변 생성"


@pytest.mark.anyio
async def test_chat_stream_uses_qwen_stream_when_retrieval_has_deterministic_artifact(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda *_args, **_kwargs: FakePipeline())
    calls = {"count": 0}
    deterministic_artifact = "검색 단계의 결정형 산출물은 최종 답변으로 노출되면 안 됩니다."
    source = {
        "filename": "직접조항.pdf",
        "doc_short": "직접조항",
        "page": 78,
        "page_end": 78,
        "chunk_id": "direct-clause-78",
        "snippet": "직접 조항 근거",
    }

    async def fake_prepare(*_args, **_kwargs):
        return [], [source], "Qwen prompt", {"graph_review_paths": [], "facts": [], "plan": {}}, [], deterministic_artifact, None

    def fake_qwen_stream(*_args, **_kwargs):
        calls["count"] += 1
        return iter(["Qwen 최종 답변"])

    monkeypatch.setattr(chat, "prepare_retrieved_context", fake_prepare)
    monkeypatch.setattr(chat, "_generate_llm_stream", fake_qwen_stream)
    created = await sessions.create_session(SessionCreateRequest(title="결정형 산출물"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(query="검사X 보상 기준을 알려주세요", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert calls["count"] == 1
    assert "Qwen 최종 답변" in stream
    assert deterministic_artifact not in stream
    assert messages[-1].content == "Qwen 최종 답변"
    assert deterministic_artifact not in messages[-1].content
    assert messages[-1].sources[0]["filename"] == source["filename"]


@pytest.mark.anyio
async def test_chat_stream_does_not_emit_done_when_turn_persistence_fails(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda *_args, **_kwargs: FakePipeline())

    async def fail_persist(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(chat, "_persist_turn", fail_persist)
    created = await sessions.create_session(SessionCreateRequest(title="저장 실패"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(query="도수치료 보상돼?", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)

    assert "event: final" not in stream
    assert "event: done" not in stream
    assert "CHAT_HISTORY_PERSIST_FAILED" in stream


@pytest.mark.anyio
async def test_chat_stream_replays_a_persisted_turn_without_duplicate_messages(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda *_args, **_kwargs: FakePipeline())
    created = await sessions.create_session(SessionCreateRequest(title="재시도"), _user(), db_session)

    first = await chat.chat_stream(
        ChatRequest(
            query="도수치료 보상돼?",
            session_id=created.id,
            model="gemma3:4b",
            turn_id="turn-retry-001",
        ),
        None,
        _user(),
        db_session,
    )
    await _stream_text(first)

    replay = await chat.chat_stream(
        ChatRequest(
            query="도수치료 보상돼?",
            session_id=created.id,
            model="gemma3:4b",
            turn_id="turn-retry-001",
        ),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(replay)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert len(messages) == 2
    assert '"replayed": true' in stream
    assert "event: final" in stream
    assert "event: done" in stream


@pytest.mark.anyio
async def test_chat_stream_restores_pending_clarification_for_the_second_turn(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda *_args, **_kwargs: FakePipeline())
    captured_contexts = []

    class FakeRegistry:
        class IntegrityReport:
            manifest_content_hash = "manifest-test-v1"

        integrity_report = IntegrityReport()

    monkeypatch.setattr(chat, "get_default_ontology_registry", lambda: FakeRegistry())

    async def fake_prepare(*_args, **kwargs):
        context = kwargs.get("conversation_context")
        captured_contexts.append(context)
        pending_slots = []
        if len(captured_contexts) == 1:
            pending_slots = [
                {
                    "slot_id": "condition-a",
                    "evidence_condition_id": "condition-a",
                    "question": "해당 조건이 확인되었나요?",
                    "allowed_values": ["yes", "no", "unknown"],
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ]
        return (
            [],
            [],
            "prompt",
            {"schema_version": 2, "clarification": {"pending_slots": pending_slots}},
            [],
            "구조화된 답변",
            None,
        )

    monkeypatch.setattr(chat, "prepare_retrieved_context", fake_prepare)
    created = await sessions.create_session(SessionCreateRequest(title="연속 확인"), _user(), db_session)

    first = await chat.chat_stream(
        ChatRequest(
            query="보상 조건을 검토해 주세요.",
            session_id=created.id,
            model="gemma3:4b",
            turn_id="turn-context-001",
        ),
        None,
        _user(),
        db_session,
    )
    first_stream = await _stream_text(first)

    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    first_messages = list(result.scalars())
    first_meta = chat._assistant_meta(first_messages[1].sources or [])
    request_id = first_meta["conversation_state"]["clarification_request"]["request_id"]

    assert "event: conversation" in first_stream
    assert request_id in first_stream
    assert '"slot_id": "condition-a"' in first_stream
    assert "topic_anchor" not in first_stream
    assert "evidence_chunk_ids" not in first_stream

    replayed_first = await chat.chat_stream(
        ChatRequest(
            query="보상 조건을 검토해 주세요.",
            session_id=created.id,
            model="gemma3:4b",
            turn_id="turn-context-001",
        ),
        None,
        _user(),
        db_session,
    )
    replay_stream = await _stream_text(replayed_first)

    assert '"replayed": true' in replay_stream
    assert "event: conversation" in replay_stream
    assert request_id in replay_stream

    second = await chat.chat_stream(
        ChatRequest(
            query="네",
            session_id=created.id,
            model="gemma3:4b",
            turn_id="turn-context-002",
            clarification={"request_id": request_id, "slot_id": "condition-a", "value": "yes"},
        ),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(second)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())
    second_meta = chat._assistant_meta(messages[3].sources or [])

    assert len(messages) == 4
    assert captured_contexts[1].kind == "clarification_response"
    assert captured_contexts[1].route_query == "보상 조건을 검토해 주세요."
    assert captured_contexts[1].assertion_draft is not None
    assert captured_contexts[1].assertion_draft.value == "yes"
    assert second_meta["conversation_state"]["user_assertions"][0]["source_message_id"] == str(messages[2].id)
    assert '"persisted": true' in stream


@pytest.mark.anyio
async def test_chat_stream_applies_auto_params_and_records_requested_values(db_session, monkeypatch) -> None:
    captured = {}

    def fake_pipeline(model, top_k, index_mode="v2_only"):
        captured["model"] = model
        captured["top_k"] = top_k
        captured["index_mode"] = index_mode
        return FakePipeline()

    monkeypatch.setattr(chat.config, "AUTO_RAG_PARAMS_MODE", "apply")
    monkeypatch.setattr(chat, "get_rag_pipeline", fake_pipeline)
    created = await sessions.create_session(SessionCreateRequest(title="자동 파라미터"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(
            query="도수치료 보상돼?",
            session_id=created.id,
            model="gemma3:4b",
            top_k=20,
            temperature=1.3,
            auto_params=True,
            index_mode="default",
        ),
        None,
        _user(),
        db_session,
    )
    async for _chunk in response.body_iterator:
        pass

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.event_type == "CHAT_QUERY"))
    audit_entry = audit_result.scalar_one()

    assert captured["top_k"] == 12
    assert captured["index_mode"] == "v2_only"
    assert audit_entry.detail["top_k"] == 10
    assert audit_entry.detail["retrieval_top_k"] == 12
    assert audit_entry.detail["temperature"] == 0.0
    assert audit_entry.detail["requested_top_k"] == 20
    assert audit_entry.detail["requested_temperature"] == 1.3
    assert audit_entry.detail["index_mode"] == "default"
    assert audit_entry.detail["effective_index_mode"] == "v2_only"
    assert audit_entry.detail["auto_params"]["effective"] is True
    assert audit_entry.detail["auto_params"]["profile"] == "coverage_judgment"
    assert audit_entry.detail["auto_params"]["top_k_strategy"] == "reranker_threshold"
    assert audit_entry.detail["rag_diagnostics"]["auto_params"]["effective_top_k"] == 10


@pytest.mark.anyio
async def test_chat_stream_can_disable_adaptive_k_separately(db_session, monkeypatch) -> None:
    captured = {}

    def fake_pipeline(model, top_k, index_mode="v2_only"):
        captured["model"] = model
        captured["top_k"] = top_k
        captured["index_mode"] = index_mode
        return FakePipeline()

    monkeypatch.setattr(chat.config, "AUTO_RAG_PARAMS_MODE", "apply")
    monkeypatch.setattr(chat.config, "AUTO_RAG_TOPK_STRATEGY", "reranker_threshold")
    monkeypatch.setattr(chat, "get_rag_pipeline", fake_pipeline)
    created = await sessions.create_session(SessionCreateRequest(title="adaptive off"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(
            query="도수치료 보상돼?",
            session_id=created.id,
            model="gemma3:4b",
            top_k=20,
            temperature=1.3,
            auto_params=True,
            adaptive_k=False,
        ),
        None,
        _user(),
        db_session,
    )
    async for _chunk in response.body_iterator:
        pass

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.event_type == "CHAT_QUERY"))
    audit_entry = audit_result.scalar_one()

    assert captured["top_k"] == 10
    assert audit_entry.detail["top_k"] == 10
    assert audit_entry.detail["retrieval_top_k"] == 10
    assert audit_entry.detail["adaptive_k"] is False
    assert audit_entry.detail["auto_params"]["top_k_strategy"] == "rule"


@pytest.mark.anyio
async def test_chat_stream_passes_reasoning_mode_and_records_audit(db_session, monkeypatch) -> None:
    pipeline = ReasoningFakePipeline()
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": pipeline)
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
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": StructuredTemplatePipeline())

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
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": StructuredTemplatePipeline())

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
    assert "■ 섹션 1️⃣" not in stream
    assert messages[1].content == "N39.3은 보상 제외로 판단됩니다."
    assert "■ 섹션" not in messages[1].content


@pytest.mark.anyio
async def test_formal_chat_stream_records_search_type_in_audit_log(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": FakePipeline())
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
async def test_general_chat_auto_routes_quickcode_and_records_strategy(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": FakePipeline())
    captured = {}

    async def fake_prepare(_pipeline, query, filters):
        captured["query"] = query
        captured["filters"] = filters
        return [], [], "quick prompt", "quick system", ["심평원"]

    monkeypatch.setattr(chat, "prepare_quickcode_context", fake_prepare)
    created = await sessions.create_session(SessionCreateRequest(title="코드"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(
            query="식도조루술 수가 코드와 점수를 알려줘",
            session_id=created.id,
            model="gemma3:4b",
        ),
        None,
        _user(),
        db_session,
    )
    async for _chunk in response.body_iterator:
        pass

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.event_type == "CHAT_QUERY"))
    audit_entry = audit_result.scalar_one()

    assert captured["filters"]["include_summary"] is True
    assert audit_entry.detail["mode"] == "general"
    assert audit_entry.detail["resolved_route"] == "quickcode"
    assert audit_entry.detail["resolved_intent"] == "procedure_code_lookup"
    assert audit_entry.detail["route_reason"] == "procedure_code_intent"
    assert "procedure_code_lookup" in audit_entry.detail["matched_cues"]


@pytest.mark.anyio
async def test_general_chat_auto_routes_formal_and_records_strategy(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": FakePipeline())
    captured = {}

    async def fake_prepare(_pipeline, query, top_k, history, filters, memo):
        captured["query"] = query
        captured["filters"] = filters
        return [], [], "formal prompt", ["약관", "표준약관"]

    monkeypatch.setattr(chat, "prepare_formal_context", fake_prepare)
    created = await sessions.create_session(SessionCreateRequest(title="약관"), _user(), db_session)

    response = await chat.chat_stream(
        ChatRequest(
            query="실손보험 약관 제12조와 별표 내용을 알려줘",
            session_id=created.id,
            model="gemma3:4b",
        ),
        None,
        _user(),
        db_session,
    )
    async for _chunk in response.body_iterator:
        pass

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.event_type == "CHAT_QUERY"))
    audit_entry = audit_result.scalar_one()

    assert captured["filters"]["search_type"] == "약관 조문 검색"
    assert audit_entry.detail["mode"] == "general"
    assert audit_entry.detail["resolved_route"] == "formal"
    assert audit_entry.detail["search_type"] == "약관 조문 검색"
    assert audit_entry.detail["route_reason"] == "clause_lookup_intent"


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
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": FakePipeline())

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
async def test_prepare_retrieved_context_uses_renderable_graph_fallback_on_graph_exception() -> None:
    _chunks, _sources, _prompt, graph_payload, warnings, _deterministic_answer, debug = await prepare_retrieved_context(
        FailingGraphPipeline(),
        (
            "이륜자동차를 타다 사고가 났습니다. 원래 이륜자동차를 타지 않는 사람인데, "
            "보험가입 후 이륜자동차를 타게 된 사실을 보험회사에 통지하지 않았습니다. "
            "이럴 경우 보상이 되는지 알려주세요."
        ),
        8,
        [],
    )

    assert warnings == [
        {
            "code": "GRAPH_RETRIEVAL_FAILED",
            "message": "GraphDB 직접 근거 조회 중 오류가 발생해 구조화 검토 경로를 fallback으로 표시합니다.",
        }
    ]
    assert graph_payload is not None
    assert graph_payload["graph_review_paths"][0]["path_type"] == "claim_condition_review"
    assert graph_payload["graph_review_paths"][0]["status"] == "missing"
    assert graph_payload["plan"]["conditions"] == ["이륜자동차 운전/탑승"]
    assert debug is not None
    assert debug.graph_result is not None


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


@pytest.mark.anyio
async def test_prepare_retrieved_context_uses_claim_terms_only_for_claim_references() -> None:
    pipeline = FakePipeline()
    history = [
        ChatMessage(
            role="assistant",
            content="보험금 계산 결과",
            sources=[_claim_snapshot_source_for_chat()],
        )
    ]

    _chunks, _sources, prompt, _graph, _warnings, _answer, _debug = await prepare_retrieved_context(
        pipeline,
        "그 계산의 공제금액이 나온 이유를 설명해 주세요",
        6,
        history,
    )

    assert "도수치료" in pipeline.last_retrieval_question
    assert "[보험금 계산 문맥 검색어]" in pipeline.last_retrieval_question
    assert "질문: 그 계산의 공제금액이 나온 이유를 설명해 주세요" in prompt

    await prepare_retrieved_context(
        pipeline,
        "N39.3 진단코드 보상 가능 여부를 알려줘",
        6,
        history,
    )

    assert pipeline.last_retrieval_question == "N39.3 진단코드 보상 가능 여부를 알려줘"



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


@pytest.mark.anyio
async def test_chat_stream_asks_clarification_for_unspecified_covered_recalculation(db_session, monkeypatch) -> None:
    def fail_pipeline(*_args, **_kwargs):
        raise AssertionError("clarification path must not call RAG")

    monkeypatch.setattr(chat, "get_rag_pipeline", fail_pipeline)
    created = await sessions.create_session(SessionCreateRequest(title="보험금 계산"), _user(), db_session)
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="보험금 계산 결과",
            sources=[_claim_snapshot_source_for_chat()],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(query="비타민D 주사를 보상한다면 얼마인가요?", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert "급여 본인부담/비급여/3대비급여" in stream
    assert "event: done" in stream
    assert messages[-2].role == "user"
    assert messages[-1].role == "assistant"


@pytest.mark.anyio
async def test_chat_stream_asks_clarification_when_multiple_claim_snapshots_are_unclear(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        chat,
        "get_rag_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no RAG")),
    )
    created = await sessions.create_session(SessionCreateRequest(title="여러 계산"), _user(), db_session)
    db_session.add_all(
        [
            ChatMessage(
                session_id=created.id,
                role="assistant",
                content="첫 계산",
                sources=[_claim_snapshot_source_for_chat(claim_id="claim-1")],
            ),
            ChatMessage(
                session_id=created.id,
                role="assistant",
                content="둘째 계산",
                sources=[
                    _claim_snapshot_source_for_chat(
                        claim_id="claim-2",
                        payable_amount="33600",
                        line_results=[
                            {
                                "line_id": "line-2",
                                "input_name": "비타민D 주사",
                                "category": "미분류 비급여",
                                "claimed_amount": "48000",
                                "deductible": "14400",
                                "payable_amount": "33600",
                                "calculation_status": "calculated",
                            }
                        ],
                    )
                ],
            ),
        ]
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(query="비타민D 주사를 비급여로 보상한다면?", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert "서로 다른 여러 계산" in stream
    assert "기준이 될 계산" in stream
    assert messages[-2].content == "비타민D 주사를 비급여로 보상한다면?"
    assert messages[-1].role == "assistant"


@pytest.mark.anyio
async def test_chat_stream_asks_clarification_when_target_line_is_ambiguous(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        chat,
        "get_rag_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no RAG")),
    )
    created = await sessions.create_session(SessionCreateRequest(title="항목 모호"), _user(), db_session)
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="보험금 계산 결과",
            sources=[
                _claim_snapshot_source_for_chat(
                    line_results=[
                        {
                            "line_id": "line-1",
                            "input_name": "비타민D 주사",
                            "category": "미분류 비급여",
                            "claimed_amount": "48000",
                        },
                        {
                            "line_id": "line-2",
                            "input_name": "비타민D 검사",
                            "category": "미분류 비급여",
                            "claimed_amount": "20000",
                        },
                    ]
                )
            ],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(query="비타민D를 비급여로 보상한다면?", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert "여러 항목" in stream
    assert "비타민D 주사" in stream
    assert "비타민D 검사" in stream
    assert messages[-2].role == "user"
    assert messages[-1].role == "assistant"


@pytest.mark.anyio
async def test_chat_stream_asks_special_status_for_fifth_generation_three_major(db_session, monkeypatch) -> None:
    def fail_run_claim_calculation(**_kwargs):
        raise AssertionError("산정특례 clarification에서는 재계산을 실행하지 않아야 합니다.")

    monkeypatch.setattr(chat, "run_claim_calculation", fail_run_claim_calculation)
    created = await sessions.create_session(SessionCreateRequest(title="산정특례 확인"), _user(), db_session)
    snapshot = _claim_snapshot_source_for_chat()
    snapshot["claim_snapshot"]["input"]["context"] = {
        "policy_generation": "5th",
        "visit_type": "outpatient",
        "coverage_topic": "실손",
        "special_calculation_status": "unknown",
    }
    snapshot["claim_snapshot"]["result"]["policy_generation"] = "5th"
    snapshot["claim_snapshot"]["result"]["special_calculation_status"] = "unknown"
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="보험금 계산 결과",
            sources=[snapshot],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(
            query="도수치료를 3대비급여로 보상한다면 다시 계산해 주세요",
            session_id=created.id,
            model="gemma3:4b",
        ),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)

    assert "event: error" not in stream
    assert "5세대 3대비급여 재계산에는 산정특례 적용 여부가 필요합니다" in stream
    assert "산정특례 적용으로" in stream
    assert "산정특례 미적용으로" in stream


@pytest.mark.anyio
async def test_chat_stream_carries_explicit_special_status_into_recalculation_context(db_session, monkeypatch) -> None:
    captured = {}

    class FakeClaimPipeline:
        pass

    def fake_pipeline(model, top_k, index_mode="v2_only"):
        captured["pipeline"] = {"model": model, "top_k": top_k, "index_mode": index_mode}
        return FakeClaimPipeline()

    def fake_run_claim_calculation(**kwargs):
        captured["context"] = kwargs["context"]
        from src.claim_calculation.models import CalculationResult

        return CalculationResult(
            claimed_amount="150000",
            payable_amount="105000",
            deductible="45000",
            formula_intent="thread_recalculation",
            executed_code="",
            applied_basis=[{"source": "테스트 근거", "content": "재계산 근거"}],
            requires_review=False,
            review_reasons=[],
            notes="재계산 완료",
            candidates=[],
            policy_generation="5th",
            special_calculation_status="applied",
            line_results=[
                {
                    "line_id": "line-1",
                    "input_name": "도수치료",
                    "category": "3대비급여",
                    "claimed_amount": "150000",
                    "deductible": "45000",
                    "payable_amount": "105000",
                    "calculation_status": "calculated",
                    "human_task_amount": "0",
                },
            ],
            calculation_status="auto_calculated",
        )

    monkeypatch.setattr(chat, "get_rag_pipeline", fake_pipeline)
    monkeypatch.setattr(chat, "run_claim_calculation", fake_run_claim_calculation)
    created = await sessions.create_session(SessionCreateRequest(title="산정특례 재계산"), _user(), db_session)
    snapshot = _claim_snapshot_source_for_chat()
    snapshot["claim_snapshot"]["input"]["context"] = {
        "policy_generation": "5th",
        "visit_type": "outpatient",
        "coverage_topic": "실손",
        "special_calculation_status": "unknown",
    }
    snapshot["claim_snapshot"]["result"]["policy_generation"] = "5th"
    snapshot["claim_snapshot"]["result"]["special_calculation_status"] = "unknown"
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="보험금 계산 결과",
            sources=[snapshot],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(
            query="도수치료를 산정특례 적용으로 3대비급여로 보상한다면 다시 계산해 주세요",
            session_id=created.id,
            model="gemma3:4b",
        ),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)

    assert "event: error" not in stream
    assert captured["context"].special_calculation_status == "applied"


@pytest.mark.anyio
async def test_chat_stream_runs_recalculation_when_category_and_target_are_clear(db_session, monkeypatch) -> None:
    captured = {}

    class FakeClaimPipeline:
        pass

    def fake_pipeline(model, top_k, index_mode="v2_only"):
        captured["pipeline"] = {"model": model, "top_k": top_k, "index_mode": index_mode}
        return FakeClaimPipeline()

    def fake_run_claim_calculation(**kwargs):
        captured["items"] = kwargs["items"]
        captured["context"] = kwargs["context"]
        from src.claim_calculation.models import CalculationResult

        return CalculationResult(
            claimed_amount="198000",
            payable_amount="143400",
            deductible="54600",
            formula_intent="thread_recalculation",
            executed_code="",
            applied_basis=[{"source": "테스트 근거", "content": "재계산 근거"}],
            requires_review=False,
            review_reasons=[],
            notes="재계산 완료",
            candidates=[],
            policy_generation="4th",
            line_results=[
                {
                    "line_id": "line-1",
                    "input_name": "도수치료",
                    "category": "3대비급여",
                    "claimed_amount": "150000",
                    "deductible": "45000",
                    "payable_amount": "105000",
                    "calculation_status": "calculated",
                    "human_task_amount": "0",
                },
                {
                    "line_id": "line-2",
                    "input_name": "비타민D 주사",
                    "category": "비급여",
                    "claimed_amount": "48000",
                    "deductible": "9600",
                    "payable_amount": "38400",
                    "calculation_status": "calculated",
                    "human_task_amount": "0",
                },
            ],
            calculation_status="auto_calculated",
        )

    monkeypatch.setattr(chat, "get_rag_pipeline", fake_pipeline)
    monkeypatch.setattr(chat, "run_claim_calculation", fake_run_claim_calculation)
    created = await sessions.create_session(SessionCreateRequest(title="재계산"), _user(), db_session)
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="보험금 계산 결과",
            sources=[_claim_snapshot_source_for_chat()],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(
            query="비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요",
            session_id=created.id,
            model="gemma3:4b",
        ),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert captured["pipeline"]["top_k"] == chat.config.CLAIM_RAG_TOP_K
    assert captured["items"][1].input_name == "비타민D 주사"
    assert captured["items"][1].nonpay_amount == "48000"
    assert captured["items"][1].user_category_hint == "비급여"
    assert "예상 지급금액: 143400원" in stream
    assert messages[-1].role == "assistant"
    assert messages[-1].sources[-1]["__kind"] == "assistant_meta"
    assert messages[-1].sources[-1]["claim_snapshot"]["result"]["payable_amount"] == "143400"
    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.event_type == "CHAT_QUERY"))
    audit_entry = audit_result.scalar_one()
    assert audit_entry.detail["resolved_route"] == "claim_follow_up"
    assert audit_entry.detail["claim_follow_up_action"] == "as_nonpay"
    assert audit_entry.detail["claim_follow_up_status"] == "calculated"
    assert audit_entry.detail["claim_follow_up_item_count"] == 2
    assert audit_entry.detail["claim_follow_up_requires_review"] is False


@pytest.mark.anyio
async def test_chat_stream_recalculation_falls_back_when_rag_pipeline_fails(db_session, monkeypatch) -> None:
    captured = {}

    def fail_pipeline(*_args, **_kwargs):
        raise RuntimeError("rag down")

    def fake_run_claim_calculation(**kwargs):
        captured["pipeline"] = kwargs["rag_pipeline"]
        from src.claim_calculation.models import CalculationResult

        return CalculationResult(
            claimed_amount="198000",
            payable_amount="143400",
            deductible="54600",
            formula_intent="thread_recalculation",
            executed_code="",
            applied_basis=[],
            requires_review=False,
            review_reasons=[],
            notes="구조화 계산만 수행",
            candidates=[],
            policy_generation="4th",
            line_results=[
                {
                    "line_id": "line-1",
                    "input_name": "도수치료",
                    "category": "3대비급여",
                    "claimed_amount": "150000",
                    "deductible": "45000",
                    "payable_amount": "105000",
                    "calculation_status": "calculated",
                    "human_task_amount": "0",
                },
                {
                    "line_id": "line-2",
                    "input_name": "비타민D 주사",
                    "category": "비급여",
                    "claimed_amount": "48000",
                    "deductible": "9600",
                    "payable_amount": "38400",
                    "calculation_status": "calculated",
                    "human_task_amount": "0",
                },
            ],
            calculation_status="auto_calculated",
        )

    monkeypatch.setattr(chat, "get_rag_pipeline", fail_pipeline)
    monkeypatch.setattr(chat, "run_claim_calculation", fake_run_claim_calculation)
    created = await sessions.create_session(SessionCreateRequest(title="재계산 fallback"), _user(), db_session)
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="보험금 계산 결과",
            sources=[_claim_snapshot_source_for_chat()],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(
            query="비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요",
            session_id=created.id,
            model="gemma3:4b",
        ),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert captured["pipeline"] is None
    assert "event: error" not in stream
    assert "예상 지급금액: 143400원" in stream
    assert messages[-1].sources[-1]["claim_snapshot"]["result"]["payable_amount"] == "143400"


@pytest.mark.anyio
async def test_chat_stream_not_covered_follow_up_persists_conditional_snapshot(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        chat,
        "get_rag_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no RAG")),
    )
    created = await sessions.create_session(SessionCreateRequest(title="보상 제외 가정"), _user(), db_session)
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="보험금 계산 결과",
            sources=[_claim_snapshot_source_for_chat()],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(query="도수치료를 보상하지 않는다면 얼마인가요?", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())
    snapshot = messages[-1].sources[-1]["claim_snapshot"]

    assert "예상 지급금액은 0원" in stream
    assert snapshot["follow_up"]["kind"] == "conditional_not_covered"
    assert snapshot["state"] == "conditional"
    assert snapshot["result"]["payable_amount"] == "0"
    assert snapshot["result"]["calculation_status"] == "conditional_follow_up"
    assert snapshot["result"]["line_results"][0]["payable_amount"] == "0"
    assert snapshot["result"]["line_results"][0]["calculation_status"] == "conditional_not_covered"


@pytest.mark.anyio
async def test_chat_stream_recalculation_skips_rag_in_explicit_isolated_e2e_mode(db_session, monkeypatch) -> None:
    """격리 브라우저 E2E의 후속 재계산은 RAG/LLM을 초기화하지 않는다."""

    captured: dict[str, object] = {}
    calls: list[tuple[object, ...]] = []

    def unexpected_pipeline(*args, **_kwargs):
        calls.append(args)
        return object()

    def fake_run_claim_calculation(**kwargs):
        captured["pipeline"] = kwargs["rag_pipeline"]
        from src.claim_calculation.models import CalculationResult

        return CalculationResult(
            claimed_amount="198000",
            payable_amount="143400",
            deductible="54600",
            formula_intent="thread_recalculation",
            executed_code="",
            applied_basis=[],
            requires_review=False,
            review_reasons=[],
            notes="구조화 계산만 수행",
            candidates=[],
            policy_generation="4th",
            line_results=[
                {
                    "line_id": "line-1",
                    "input_name": "도수치료",
                    "category": "3대비급여",
                    "claimed_amount": "150000",
                    "deductible": "45000",
                    "payable_amount": "105000",
                    "calculation_status": "calculated",
                    "human_task_amount": "0",
                },
                {
                    "line_id": "line-2",
                    "input_name": "비타민D 주사",
                    "category": "비급여",
                    "claimed_amount": "48000",
                    "deductible": "9600",
                    "payable_amount": "38400",
                    "calculation_status": "calculated",
                    "human_task_amount": "0",
                },
            ],
            calculation_status="auto_calculated",
        )

    monkeypatch.setenv("INSURANCE_RAG_ISOLATED_E2E", "1")
    monkeypatch.setattr(chat, "get_rag_pipeline", unexpected_pipeline)
    monkeypatch.setattr(chat, "run_claim_calculation", fake_run_claim_calculation)
    created = await sessions.create_session(SessionCreateRequest(title="격리 재계산"), _user(), db_session)
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="보험금 계산 결과",
            sources=[_claim_snapshot_source_for_chat()],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(
            query="비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요",
            session_id=created.id,
            model="gemma3:4b",
        ),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)

    assert calls == []
    assert captured["pipeline"] is None
    assert "예상 지급금액: 143400원" in stream


@pytest.mark.anyio
async def test_fifth_standard_authority_reply_persists_without_mutating_history(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda model, top_k, index_mode="v2_only": FakePipeline())
    captured: dict[str, object] = {}
    authority_answer = "5세대 표준약관은 등록되어 있으며, 현재 답변은 해당 표준약관의 직접 조항을 근거로 합니다."

    async def fake_prepare(*_args, **kwargs):
        captured["policy_generation"] = kwargs.get("policy_generation")
        return [], [], "prompt", {"graph_review_paths": [], "facts": [], "plan": {}}, [], authority_answer, None

    monkeypatch.setattr(chat, "prepare_retrieved_context", fake_prepare)
    created = await sessions.create_session(SessionCreateRequest(title="5세대 표준약관"), _user(), db_session)
    prior_content = "과거 저장 답변은 감사 보존을 위해 변경하지 않습니다."
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content=prior_content,
            sources=[],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(
            query="노화현상으로 인한 탈모는 보상 가능한가요?",
            session_id=created.id,
            model="gemma3:4b",
            policy_generation="5th",
        ),
        None,
        _user(),
        db_session,
    )
    stream = await _stream_text(response)
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert captured["policy_generation"] == "5th"
    assert messages[0].content == prior_content
    assert messages[-1].content == "실손 답변"
    assert authority_answer not in messages[-1].content
