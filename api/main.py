"""FastAPI app. `make api` runs `uvicorn api.main:app --reload --port 8000`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.routers import router
from db.bootstrap import create_all
from db.models import IngestMetadata
from db.session import get_engine


class NotIngestedError(RuntimeError):
    pass


async def latest_ingest_metadata(session: AsyncSession) -> IngestMetadata | None:
    """Split out from lifespan() so the startup guard's actual logic is testable
    against an arbitrary session/engine, independent of db.session.get_engine()'s
    process-wide singleton (which the test suite already pins via DATABASE_URL at
    import time -- see tests/test_lifespan.py)."""
    return (
        await session.execute(select(IngestMetadata).order_by(IngestMetadata.pipeline_run_at.desc()).limit(1))
    ).scalar_one_or_none()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    if engine.dialect.name == "sqlite":
        # Postgres is migrated with Alembic (`make migrate`); SQLite dev/test just
        # creates tables from the ORM metadata directly (db/bootstrap.py).
        await create_all(engine)

    # docs/DECISIONS.md "Synthetic data is no longer the silent default": refuse to
    # serve a database nobody has ever actually ingested into, rather than silently
    # start against empty tables (every endpoint would just 404/empty-list its way
    # through a broken-looking app with no indication why).
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        latest = await latest_ingest_metadata(session)
    if latest is None:
        raise NotIngestedError(
            "No ingest_metadata row found -- the database has never been seeded. "
            "Run `python -m pipeline.run_all` (or `make pipeline`) first."
        )
    app.state.data_source = latest.data_source
    app.state.dataset_snapshot_date = latest.dataset_snapshot_date
    app.state.pipeline_run_at = latest.pipeline_run_at.isoformat()

    yield


app = FastAPI(title="Gaffer API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
