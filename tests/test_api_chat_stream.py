import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.db import Base
from src.api.models import ChatMessage
from src.api.routes import chat, sessions
from src.api.schemas.chat import ChatRequest
from src.api.schemas.sessions import SessionCreateRequest
from src.auth.users import User


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


class FakePipeline:
    def __init__(self):
        self.llm = FakeLLM()
        self.graph_enabled = False
        self.graph_retriever = None

    def retrieve_hits(self, question, top_k=None, doc_filter=None, return_debug=False, graph_hits=None):
        return (
            [
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
                    },
                )()
            ],
            None,
        )

    def build_prompt(self, question, chunks, graph_context=None):
        return f"질문: {question}\n근거 수: {len(chunks)}"


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
