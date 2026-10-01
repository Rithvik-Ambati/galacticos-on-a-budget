"""Dialect-aware embedding column.

docs/DESIGN.md section 4 names PostgreSQL 16 + pgvector >= 0.8 as the production
vector store (next to relational filters, one SQL query and one transaction).

docs/DECISIONS.md records why this file exists: Docker Desktop's Linux engine
could not be started in the sandbox this project was first built in, so no
live Postgres was reachable to test against. VectorType stores the pgvector
`vector(dim)` column on Postgres (HNSW cosine index, per section 6) and falls
back to a JSON-encoded float array on SQLite so the same models and the same
rag/ retrieval code can run against `sqlite+aiosqlite` for local tests. The
SQLite path never claims pgvector's index performance — rag/dense.py does the
cosine scan in Python for that dialect. Swap DATABASE_URL to Postgres and
nothing else changes.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.types import JSON, TypeDecorator, UserDefinedType


class _PgVector(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dim})"

    def bind_processor(self, dialect: Any) -> Any:
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(str(float(v)) for v in value) + "]"

        return process

    def result_processor(self, dialect: Any, coltype: Any) -> Any:
        def process(value: str | None) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return value
            return [float(v) for v in value.strip("[]").split(",") if v]

        return process


class VectorType(TypeDecorator[list[float]]):
    """Vector column: pgvector on Postgres, JSON array on everything else."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgVector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[float] | None, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        if isinstance(value, str):
            return list(json.loads(value))
        return list(value)
