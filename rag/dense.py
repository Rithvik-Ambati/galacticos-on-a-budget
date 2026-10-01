"""Dense vector search. Postgres path uses pgvector's cosine operator in SQL (one query,
one transaction, per docs/DESIGN.md section 4); the SQLite dev/test fallback scans in
Python (docs/DECISIONS.md) -- fine at this corpus size, never claimed to be the HNSW
path's performance.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Document


@dataclass
class DenseHit:
    doc_id: str
    score: float  # cosine similarity, higher is better


async def search(
    session: AsyncSession, query_embedding: list[float], top_k: int = 50, doc_type: str | None = None
) -> list[DenseHit]:
    stmt = select(Document.doc_id, Document.embedding).where(Document.embedding.is_not(None))
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type)

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        # pgvector cosine distance operator; 1 - distance = similarity.
        from sqlalchemy import literal

        rows = (
            await session.execute(
                select(Document.doc_id, (1 - Document.embedding.op("<=>")(literal(query_embedding))).label("sim"))
                .where(Document.embedding.is_not(None))
                .order_by("sim DESC")
                .limit(top_k)
            )
        ).all()
        return [DenseHit(doc_id, float(sim)) for doc_id, sim in rows]

    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    q = np.array(query_embedding)
    q_norm = q / (np.linalg.norm(q) or 1.0)

    scored = []
    for doc_id, embedding in rows:
        v = np.array(embedding)
        v_norm = v / (np.linalg.norm(v) or 1.0)
        scored.append((doc_id, float(np.dot(q_norm, v_norm))))

    scored.sort(key=lambda t: -t[1])
    return [DenseHit(doc_id, score) for doc_id, score in scored[:top_k]]
