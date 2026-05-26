import csv
import io

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.db import Base
from src.api.exceptions import InvalidFormatException, SessionNotFoundException
from src.api.models import ChatMessage
from src.api.routes import sessions
from src.api.schemas.sessions import SessionCreateRequest
from src.auth.users import User


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'export.db'}")

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


def _user(username: str = "employee01") -> User:
    return User(username, "hash", "employee", username, "2026-05-20T00:00:00Z", "2026-05-20T00:00:00Z")


async def _seed_session(db_session):
    created = await sessions.create_session(SessionCreateRequest(title="Export Test"), _user(), db_session)
    db_session.add_all(
        [
            ChatMessage(session_id=created.id, role="user", content="질문"),
            ChatMessage(session_id=created.id, role="assistant", content="답변", sources=[{"filename": "약관.pdf", "page": 3}]),
        ]
    )
    await db_session.commit()
    return created.id


@pytest.mark.anyio
async def test_export_txt_format(db_session) -> None:
    session_id = await _seed_session(db_session)

    response = await sessions.export_session(None, session_id, "txt", _user(), db_session)

    assert response.media_type.startswith("text/plain")
    assert "신한EZ손해보험" in response.body.decode("utf-8")


@pytest.mark.anyio
async def test_export_csv_format(db_session) -> None:
    session_id = await _seed_session(db_session)

    response = await sessions.export_session(None, session_id, "csv", _user(), db_session)
    rows = list(csv.reader(io.StringIO(response.body.decode("utf-8"))))

    assert rows[0] == ["timestamp", "role", "content", "sources"]
    assert rows[2][3] == "약관.pdf (p.3)"


@pytest.mark.anyio
async def test_export_json_format(db_session) -> None:
    session_id = await _seed_session(db_session)

    response = await sessions.export_session(None, session_id, "json", _user(), db_session)

    assert response.status_code == 200
    assert "application/json" in response.media_type


@pytest.mark.anyio
async def test_export_invalid_format(db_session) -> None:
    session_id = await _seed_session(db_session)

    with pytest.raises(InvalidFormatException):
        await sessions.export_session(None, session_id, "xml", _user(), db_session)


@pytest.mark.anyio
async def test_export_missing_session(db_session) -> None:
    with pytest.raises(SessionNotFoundException):
        await sessions.export_session(None, "missing", "txt", _user(), db_session)
