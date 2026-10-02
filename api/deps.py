"""Shared engine/graph singletons and the DB session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.session import get_engine


@lru_cache
def get_graph() -> Any:
    from graph.graph import build_graph

    return build_graph(get_engine())


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session
