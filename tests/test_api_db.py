from sqlalchemy.pool import NullPool

from src.api import db


def test_engine_kwargs_uses_nullpool_for_sqlite(monkeypatch) -> None:
    monkeypatch.setattr(db, "_database_url", lambda: "sqlite+aiosqlite:///tmp/test.db")

    kwargs = db._engine_kwargs()

    assert kwargs["future"] is True
    assert kwargs["poolclass"] is NullPool
    assert kwargs["connect_args"] == {"timeout": 30}


def test_engine_kwargs_keeps_default_pool_for_non_sqlite(monkeypatch) -> None:
    monkeypatch.setattr(db, "_database_url", lambda: "postgresql+asyncpg://user:pass@localhost/db")

    kwargs = db._engine_kwargs()

    assert kwargs == {"future": True}
