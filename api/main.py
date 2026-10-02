"""FastAPI app. `make api` runs `uvicorn api.main:app --reload --port 8000`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import router
from db.bootstrap import create_all
from db.session import get_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    if engine.dialect.name == "sqlite":
        # Postgres is migrated with Alembic (`make migrate`); SQLite dev/test just
        # creates tables from the ORM metadata directly (db/bootstrap.py).
        await create_all(engine)
    yield


app = FastAPI(title="Lineup Lab API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
