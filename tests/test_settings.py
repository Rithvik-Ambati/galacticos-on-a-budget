"""Tests for config/settings.py URL normalization."""

from config.settings import Settings


def test_bare_postgresql_scheme_rewritten_to_asyncpg() -> None:
    s = Settings(database_url="postgresql://user:pw@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://user:pw@host:5432/db"


def test_postgres_scheme_rewritten_to_asyncpg() -> None:
    s = Settings(database_url="postgres://user:pw@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://user:pw@host:5432/db"


def test_already_qualified_asyncpg_url_passes_through() -> None:
    s = Settings(database_url="postgresql+asyncpg://user:pw@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://user:pw@host:5432/db"


def test_sqlite_url_passes_through() -> None:
    s = Settings(database_url="sqlite+aiosqlite:///./dev.db")
    assert s.database_url == "sqlite+aiosqlite:///./dev.db"


def test_readonly_url_is_also_normalized() -> None:
    s = Settings(database_url_readonly="postgresql://user:pw@host:5432/db")
    assert s.database_url_readonly == "postgresql+asyncpg://user:pw@host:5432/db"
