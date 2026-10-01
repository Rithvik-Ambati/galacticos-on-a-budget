"""Create all tables directly from the ORM metadata.

For SQLite dev/test (`make migrate` runs real Alembic against Postgres); this is the
quick path pipeline/ and the test suite use so they don't need Alembic wired up
against a database that, in this environment, was never reachable (docs/DECISIONS.md).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from db.models import Base


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
