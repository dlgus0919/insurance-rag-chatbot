import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.db import Base
from src.api.models import ChatMessage, ChatSession
from src.api.routes import sessions
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


def _user(username: str) -> User:
    return User(
        username=username,
        password_hash="hash",
        role="employee",
        display_name=username,
        created_at="2026-05-20T00:00:00+00:00",
        password_updated_at="2026-05-20T00:00:00+00:00",
    )


@pytest.mark.anyio
async def test_session_crud_user_isolation_and_json_sources(db_session) -> None:
    user = _user("employee01")
    other = _user("employee02")

    created = await sessions.create_session(SessionCreateRequest(title="보상 문의"), user, db_session)
    other_created = await sessions.create_session(SessionCreateRequest(title="다른 사용자"), other, db_session)

    db_session.add_all(
        [
            ChatMessage(session_id=created.id, role="user", content="질문"),
            ChatMessage(
                session_id=created.id,
                role="assistant",
                content="답변",
                sources=[{"filename": "약관.pdf", "page": 14}],
            ),
        ]
    )
    await db_session.commit()

    user_sessions = await sessions.list_sessions(user, db_session)
    messages = await sessions.list_messages(created.id, user, db_session)

    assert [item.id for item in user_sessions] == [created.id]
    assert other_created.id not in [item.id for item in user_sessions]
    assert user_sessions[0].message_count == 2
    assert messages[1].sources == [{"filename": "약관.pdf", "page": 14}]

    await sessions.delete_session(created.id, user, db_session)
    remaining = await db_session.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.session_id == created.id))
    assert remaining == 0


@pytest.mark.anyio
async def test_sessions_sort_by_last_activity_and_messages_have_stable_tie_breaker(db_session) -> None:
    user = _user("employee01")
    older = ChatSession(user_id=user.username, title="오래된 세션")
    newer = ChatSession(user_id=user.username, title="새 세션")
    db_session.add_all([older, newer])
    await db_session.commit()

    db_session.add_all(
        [
            ChatMessage(session_id=older.id, role="user", content="오래된 첫 질문"),
            ChatMessage(session_id=older.id, role="assistant", content="오래된 최신 답변"),
        ]
    )
    await db_session.commit()

    listed = await sessions.list_sessions(user, db_session)
    messages = await sessions.list_messages(older.id, user, db_session)

    assert listed[0].id == older.id
    assert listed[0].last_activity_at >= listed[1].last_activity_at
    assert [message.content for message in messages] == ["오래된 첫 질문", "오래된 최신 답변"]
