import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.db import Base
from src.api.deps import log_audit_event
from src.api.models import AuditLog
from src.api.routes import admin
from src.auth.users import ROLE_ADMIN, ROLE_EMPLOYEE, User


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")

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


def _user(role: str = ROLE_ADMIN) -> User:
    return User(
        username="admin" if role == ROLE_ADMIN else "employee01",
        password_hash="hash",
        role=role,
        display_name=role,
        created_at="2026-05-20T00:00:00+00:00",
        password_updated_at="2026-05-20T00:00:00+00:00",
    )


@pytest.mark.anyio
async def test_log_audit_event_persists_json_detail(db_session) -> None:
    await log_audit_event(
        db_session,
        "CHAT_QUERY",
        user_id="employee01",
        ip_address="127.0.0.1",
        detail={"model": "gemma3:4b", "mode": "quickcode"},
    )

    rows = list((await db_session.execute(select(AuditLog))).scalars())

    assert rows[0].event_type == "CHAT_QUERY"
    assert rows[0].detail == {"model": "gemma3:4b", "mode": "quickcode"}


@pytest.mark.anyio
async def test_admin_stats_and_logs_use_real_audit_data(db_session) -> None:
    await log_audit_event(db_session, "CHAT_QUERY", "admin", "127.0.0.1", {"mode": "general", "model": "m"})
    await log_audit_event(db_session, "CHAT_QUERY", "admin", "127.0.0.1", {"mode": "quickcode", "model": "m"})
    await log_audit_event(db_session, "LOGIN_SUCCESS", "admin", "127.0.0.1", {"role": "admin"})

    stats = await admin.stats(_user(), db_session)
    logs = await admin.logs(1, 2, _user(), db_session)

    assert stats["total_queries"] == 2
    assert stats["mode_distribution"]["general"] == 1
    assert stats["mode_distribution"]["quickcode"] == 1
    assert stats["mode_distribution"]["formal"] == 0
    assert logs["page"] == 1
    assert logs["page_size"] == 2
    assert logs["total"] == 3
    assert len(logs["items"]) == 2
    assert logs["items"][0]["detail"]


@pytest.mark.anyio
async def test_require_admin_rejects_non_admin() -> None:
    with pytest.raises(Exception):
        await admin.require_admin(_user(ROLE_EMPLOYEE))
