"""Async SQLite database setup for API-owned chat history."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.api.settings import get_api_settings


class Base(DeclarativeBase):
    """Base class for API database models."""


def _database_url() -> str:
    return get_api_settings().database_url


engine = create_async_engine(_database_url(), future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _) -> None:
    """Enable ON DELETE CASCADE support for SQLite connections."""

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def init_db() -> None:
    """Create API-owned tables if they do not already exist."""

    import src.api.models  # noqa: F401 - ensure model metadata is registered

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session."""

    async with AsyncSessionLocal() as session:
        yield session
