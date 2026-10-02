"""Embedding-model selection benchmark. docs/DESIGN.md section 4: the recall-vs-latency
comparison that `rag/embeddings.py` cites as the reason BAAI/bge-small-en-v1.5 (not
bge-base or e5-base) is the production default.

Same Recall@10/MRR/nDCG@10 metrics as `evals/retrieval_eval.py`, computed dense-only
(no BM25/rerank -- isolating the embedding model itself), for each candidate model,
plus p50/p95 query-embedding latency. Embeddings are computed in memory for this
comparison only and never written back to `documents.embedding` -- that column stays
whatever `pipeline.documents`/the production embedder last wrote.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Document
from evals.retrieval_eval import GoldenQuery, _mrr, _ndcg_at_k, _recall_at_k, load_golden
from rag.embeddings import _load_model

CANDIDATE_MODELS = ("BAAI/bge-small-en-v1.5", "BAAI/bge-base-en-v1.5", "intfloat/e5-base-v2")
TOP_K = 10


@dataclass
class ModelBenchmark:
    model_name: str
    recall_at_10: float
    mrr: float
    ndcg_at_10: float
    latency_p50_ms: float
    latency_p95_ms: float
    n_queries: int


@dataclass
class EmbeddingBenchmarkReport:
    by_model: dict[str, ModelBenchmark] = field(default_factory=dict)
    best_model: str | None = None  # by nDCG@10


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))
    return ordered[idx]


async def _load_corpus(session: AsyncSession) -> list[tuple[str, str]]:
    rows = (await session.execute(select(Document))).scalars().all()
    return [(d.doc_id, d.text) for d in rows]


async def _benchmark_one_model(
    model_name: str, golden: list[GoldenQuery], corpus: list[tuple[str, str]]
) -> ModelBenchmark:
    model = _load_model(model_name)

    # Corpus encoded once, batched, for speed -- this is purely an in-memory
    # ranking matrix for THIS comparison and is never written to
    # db.models.Document.embedding (that column stays whatever the production
    # pipeline's own embedder last set). Per-query encoding below stays one-at-a-
    # time, matching how a real query arrives in production, so the measured
    # latency is representative.
    doc_ids = [doc_id for doc_id, _text in corpus]
    doc_vectors = np.asarray(
        model.encode([text for _doc_id, text in corpus], normalize_embeddings=True, batch_size=64)
    )
    doc_norms = doc_vectors / np.clip(np.linalg.norm(doc_vectors, axis=1, keepdims=True), 1e-9, None)

    recalls, mrrs, ndcgs, latencies_ms = [], [], [], []
    for gq in golden:
        start = time.perf_counter()
        query_vec = np.asarray(model.encode(gq.query, normalize_embeddings=True))
        latencies_ms.append((time.perf_counter() - start) * 1000)

        query_norm = query_vec / (np.linalg.norm(query_vec) or 1.0)
        scores = doc_norms @ query_norm
        ranked_idx = np.argsort(-scores)[:TOP_K]
        retrieved = [doc_ids[i] for i in ranked_idx]

        recalls.append(_recall_at_k(retrieved, gq.relevant_doc_ids, TOP_K))
        mrrs.append(_mrr(retrieved, gq.relevant_doc_ids))
        ndcgs.append(_ndcg_at_k(retrieved, gq.relevant_doc_ids, TOP_K))

    return ModelBenchmark(
        model_name=model_name,
        recall_at_10=round(sum(recalls) / len(recalls), 4),
        mrr=round(sum(mrrs) / len(mrrs), 4),
        ndcg_at_10=round(sum(ndcgs) / len(ndcgs), 4),
        latency_p50_ms=round(_percentile(latencies_ms, 50), 2),
        latency_p95_ms=round(_percentile(latencies_ms, 95), 2),
        n_queries=len(golden),
    )


async def run_embedding_benchmark(
    session: AsyncSession, golden: list[GoldenQuery] | None = None, models: tuple[str, ...] = CANDIDATE_MODELS
) -> EmbeddingBenchmarkReport:
    golden = golden if golden is not None else load_golden()
    report = EmbeddingBenchmarkReport()
    if not golden:
        return report

    corpus = await _load_corpus(session)
    if not corpus:
        return report

    for model_name in models:
        report.by_model[model_name] = await _benchmark_one_model(model_name, golden, corpus)

    if report.by_model:
        report.best_model = max(report.by_model, key=lambda m: report.by_model[m].ndcg_at_10)
    return report


def render_accuracy_table(report: EmbeddingBenchmarkReport) -> str:
    if not report.by_model:
        return "_No embedding models benchmarked (empty golden set or empty corpus)._"
    lines = ["| Model | Recall@10 | MRR | nDCG@10 | n_queries |", "|---|---|---|---|---|"]
    for name, m in report.by_model.items():
        ndcg_cell = f"**{m.ndcg_at_10:.4f}**" if name == report.best_model else f"{m.ndcg_at_10:.4f}"
        lines.append(f"| {name} | {m.recall_at_10:.4f} | {m.mrr:.4f} | {ndcg_cell} | {m.n_queries} |")
    return "\n".join(lines)


def render_latency_table(report: EmbeddingBenchmarkReport) -> str:
    if not report.by_model:
        return "_No embedding models benchmarked (empty golden set or empty corpus)._"
    lines = ["| Model | p50 latency (ms) | p95 latency (ms) |", "|---|---|---|"]
    for name, m in report.by_model.items():
        lines.append(f"| {name} | {m.latency_p50_ms:.2f} | {m.latency_p95_ms:.2f} |")
    return "\n".join(lines)


if __name__ == "__main__":
    import asyncio
    import json

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from db.session import get_engine

    async def _main() -> None:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with session_factory() as session:
            report = await run_embedding_benchmark(session)

        if not report.by_model:
            print(
                "No golden retrieval queries (evals/golden/retrieval_queries.jsonl is "
                "empty or corpus is empty) -- skipping embedding benchmark."
            )
            raise SystemExit(0)

        print("## Accuracy\n")
        print(render_accuracy_table(report))
        print("\n## Latency\n")
        print(render_latency_table(report))

        reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        with open(os.path.join(reports_dir, "embedding_benchmark.json"), "w", encoding="utf-8") as f:
            json.dump(
                {name: vars(m) for name, m in report.by_model.items()} | {"best_model": report.best_model},
                f,
                indent=2,
            )

    asyncio.run(_main())
