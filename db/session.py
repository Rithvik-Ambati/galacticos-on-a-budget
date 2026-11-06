"""Async engine/session factory. Reads DATABASE_URL from config.settings."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import get_settings

# Neither asyncio nor asyncpg apply a connect timeout by default, so a
# network-level hang (bad hostname, dropped route) otherwise blocks the
# calling request forever instead of failing with a clear error.
CONNECT_TIMEOUT_SECONDS = 10


def make_engine(url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    resolved_url = url or settings.database_url
    connect_args = {"timeout": CONNECT_TIMEOUT_SECONDS} if resolved_url.startswith("postgresql") else {}
    return create_async_engine(resolved_url, echo=False, connect_args=connect_args)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
