"""Retrieval eval runner. docs/DESIGN.md section 12: Recall@10, MRR, nDCG, ablation
across BM25 / dense / hybrid / hybrid+rerank, against the human-written golden set.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from rag.embeddings import Embedder
from rag.rerank import Reranker
from rag.retriever import retrieve_ablation

METHODS = ("bm25", "dense", "hybrid", "hybrid_rerank")
DEFAULT_GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden", "retrieval_queries.jsonl")


@dataclass
class GoldenQuery:
    query: str
    relevant_doc_ids: set[str]
    doc_type: str | None = None


@dataclass
class MethodMetrics:
    recall_at_10: float
    mrr: float
    ndcg_at_10: float
    n_queries: int


@dataclass
class RetrievalEvalReport:
    by_method: dict[str, MethodMetrics] = field(default_factory=dict)
    best_method: str | None = None


def load_golden(path: str = DEFAULT_GOLDEN_PATH) -> list[GoldenQuery]:
    if not os.path.exists(path):
        return []
    queries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("is_example"):
                continue  # evals/golden/README.md: illustrative rows, never scored
            queries.append(
                GoldenQuery(
                    query=row["query"],
                    relevant_doc_ids=set(row["relevant_doc_ids"]),
                    doc_type=row.get("doc_type"),
                )
            )
    return queries


def _recall_at_k(retrieved: list[str], relevant: set[str], k: int = 10) -> float:
    if not relevant:
        return 0.0
    hit = len(set(retrieved[:k]) & relevant)
    return hit / len(relevant)


def _mrr(retrieved: list[str], relevant: set[str]) -> float:
    for rank, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(retrieved: list[str], relevant: set[str], k: int = 10) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, doc_id in enumerate(retrieved[:k]) if doc_id in relevant)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


async def run_retrieval_eval(
    session: AsyncSession,
    golden: list[GoldenQuery] | None = None,
    *,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> RetrievalEvalReport:
    golden = golden if golden is not None else load_golden()
    report = RetrievalEvalReport()
    if not golden:
        return report

    for method in METHODS:
        if method in ("dense", "hybrid", "hybrid_rerank") and embedder is None:
            continue  # can't evaluate a dense-dependent method without an embedder
        if method == "hybrid_rerank" and reranker is None:
            continue

        recalls, mrrs, ndcgs = [], [], []
        for gq in golden:
            retrieved = await retrieve_ablation(
                session, gq.query, method, embedder=embedder, reranker=reranker, doc_type=gq.doc_type, top_k=10
            )
            recalls.append(_recall_at_k(retrieved, gq.relevant_doc_ids))
            mrrs.append(_mrr(retrieved, gq.relevant_doc_ids))
            ndcgs.append(_ndcg_at_k(retrieved, gq.relevant_doc_ids))

        report.by_method[method] = MethodMetrics(
            recall_at_10=round(sum(recalls) / len(recalls), 4),
            mrr=round(sum(mrrs) / len(mrrs), 4),
            ndcg_at_10=round(sum(ndcgs) / len(ndcgs), 4),
            n_queries=len(golden),
        )

    if report.by_method:
        report.best_method = max(report.by_method, key=lambda m: report.by_method[m].ndcg_at_10)
    return report


def render_ablation_table(report: RetrievalEvalReport) -> str:
    """Markdown table of Recall@10/MRR/nDCG@10 per method, best nDCG@10 bolded --
    the exact artifact docs/PROGRESS.md and README.md's evaluation-results section
    link to (never hand-typed numbers)."""
    if not report.by_method:
        return "_No retrieval methods evaluated (empty golden set or no embedder/reranker available)._"

    lines = [
        "| Method | Recall@10 | MRR | nDCG@10 | n_queries |",
        "|---|---|---|---|---|",
    ]
    for method in METHODS:
        if method not in report.by_method:
            continue
        m = report.by_method[method]
        ndcg_cell = f"**{m.ndcg_at_10:.4f}**" if method == report.best_method else f"{m.ndcg_at_10:.4f}"
        lines.append(f"| {method} | {m.recall_at_10:.4f} | {m.mrr:.4f} | {ndcg_cell} | {m.n_queries} |")
    return "\n".join(lines)


if __name__ == "__main__":
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from db.session import get_engine

    async def _main() -> None:
        golden = load_golden()
        if not golden:
            print(
                f"No golden set at {DEFAULT_GOLDEN_PATH} (0 queries) -- skipping retrieval eval. "
                "evals/golden/README.md explains the format."
            )
            return

        embedder = reranker = None
        try:
            from rag.embeddings import get_embedder
            from rag.rerank import get_reranker

            embedder, reranker = get_embedder(), get_reranker()
        except Exception as exc:  # pragma: no cover - environment-dependent
            print(f"Embedding/reranker models unavailable ({exc}); running BM25-only ablation.")

        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with session_factory() as session:
            report = await run_retrieval_eval(session, golden, embedder=embedder, reranker=reranker)
        print(render_ablation_table(report))

    asyncio.run(_main())
