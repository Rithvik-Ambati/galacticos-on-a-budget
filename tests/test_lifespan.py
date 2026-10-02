"""docs/DECISIONS.md "Synthetic data is no longer the silent default": the API must
refuse to boot against a database nobody has ever run the pipeline against, and must
record which data source is live for /health and the frontend's demo-data banner.

db.session.get_engine() is a process-wide singleton that tests/test_api.py (and
every other test module that touches the API) already pins via DATABASE_URL at
import time. Rather than fight that, these tests monkeypatch db.session's module
globals directly to point at a throwaway engine for the duration of each test, then
restore them -- real end-to-end coverage of api.main.lifespan() itself, not just the
extracted helper, without disturbing any other test's shared engine state.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import db.session as db_session
from api.main import NotIngestedError, latest_ingest_metadata, lifespan
from db.bootstrap import create_all
from db.models import IngestMetadata


@pytest.fixture
async def isolated_engine():
    engine = create_async_engine("sqlite+aiosqlite://")
    await create_all(engine)
    old_engine, old_factory = db_session._engine, db_session._session_factory
    db_session._engine = engine
    db_session._session_factory = None
    try:
        yield engine
    finally:
        db_session._engine, db_session._session_factory = old_engine, old_factory
        await engine.dispose()


async def test_latest_ingest_metadata_returns_none_when_empty(isolated_engine) -> None:
    session_factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    async with session_factory() as session:
        assert await latest_ingest_metadata(session) is None


async def test_latest_ingest_metadata_returns_the_most_recent_row(isolated_engine) -> None:
    session_factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            IngestMetadata(
                data_source="synthetic", pipeline_run_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
            )
        )
        session.add(
            IngestMetadata(
                data_source="real",
                dataset_snapshot_date="2026-06-28",
                pipeline_run_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
            )
        )
        await session.commit()
    async with session_factory() as session:
        latest = await latest_ingest_metadata(session)
    assert latest is not None
    assert latest.data_source == "real"
    assert latest.dataset_snapshot_date == "2026-06-28"


async def test_lifespan_refuses_to_start_with_no_metadata(isolated_engine) -> None:
    app = FastAPI()
    with pytest.raises(NotIngestedError):
        async with lifespan(app):
            pass  # pragma: no cover -- should never be reached


async def test_lifespan_exposes_data_source_on_app_state(isolated_engine) -> None:
    session_factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(IngestMetadata(data_source="synthetic"))
        await session.commit()

    app = FastAPI()
    async with lifespan(app):
        assert app.state.data_source == "synthetic"
        assert app.state.pipeline_run_at is not None
