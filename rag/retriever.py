"""Full hybrid retrieval pipeline. docs/DESIGN.md section 8:

query -> (optional rewrite) -> BM25 top-50 + dense top-50 (with metadata filters)
-> RRF fusion (k=60) -> cross-encoder rerank -> top-5.

Low-relevance handling: if the top rerank score is below threshold, rewrite and retry
once; if still low, signal the caller to fall back (route to the SQL tool, or answer
"not enough data") rather than hand the LLM irrelevant context (CLAUDE.md rule 1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Document
from observability import traced_span
from rag.bm25 import Bm25Index
from rag.dense import search as dense_search
from rag.embeddings import Embedder
from rag.fusion import rrf_fuse
from rag.rerank import Reranker

RELEVANCE_THRESHOLD = 0.0  # bge-reranker-base logit; tune against evals/golden once written
TOP_K_PER_METHOD = 50
TOP_K_FINAL = 5


@dataclass
class RetrievedDoc:
    doc_id: str
    text: str
    metadata: dict[str, object]
    score: float


@dataclass
class RetrievalResult:
    docs: list[RetrievedDoc]
    low_relevance: bool
    rewritten_query: str | None
    method: str  # "hybrid_rerank" | "rewrite_retry" | "fallback"


async def _load_corpus(
    session: AsyncSession, doc_type: str | None, nationality: str | None
) -> list[Document]:
    stmt = select(Document)
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type)
    docs = (await session.execute(stmt)).scalars().all()
    if nationality is not None:
        docs = [d for d in docs if d.metadata_json.get("nationality") == nationality]
    return list(docs)


async def _single_pass(
    session: AsyncSession,
    query: str,
    embedder: Embedder | None,
    reranker: Reranker | None,
    doc_type: str | None,
    nationality: str | None,
) -> list[RetrievedDoc]:
    corpus = await _load_corpus(session, doc_type, nationality)
    if not corpus:
        return []
    by_id = {d.doc_id: d for d in corpus}

    bm25_hits = Bm25Index.from_documents([(d.doc_id, d.text) for d in corpus]).search(query, TOP_K_PER_METHOD)
    bm25_ranked = [h.doc_id for h in bm25_hits]

    dense_ranked: list[str] = []
    if embedder is not None:
        dense_hits = await dense_search(session, embedder(query), TOP_K_PER_METHOD, doc_type)
        dense_ranked = [h.doc_id for h in dense_hits if h.doc_id in by_id]

    fused = rrf_fuse([lst for lst in (bm25_ranked, dense_ranked) if lst])
    top_fused = [doc_id for doc_id, _score in fused[:TOP_K_PER_METHOD]]
    if not top_fused:
        return []

    if reranker is not None:
        reranked = reranker(query, [(doc_id, by_id[doc_id].text) for doc_id in top_fused])
    else:
        reranked = [(doc_id, score) for doc_id, score in fused if doc_id in top_fused]

    return [
        RetrievedDoc(doc_id=doc_id, text=by_id[doc_id].text, metadata=by_id[doc_id].metadata_json, score=score)
        for doc_id, score in reranked[:TOP_K_FINAL]
    ]


def _default_rewrite(query: str) -> str:
    """Stub rewrite: without a real LLM configured, there's nothing meaningfully
    different to try, so this is the identity function -- the retry step still runs
    (and is tested), it just can't improve on a stub's own first attempt. A real
    llm.provider.Provider swapped in here is where an actual rewrite would happen."""
    return query


async def retrieve_ablation(
    session: AsyncSession,
    query: str,
    method: str,
    *,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    doc_type: str | None = None,
    top_k: int = TOP_K_FINAL,
) -> list[str]:
    """One named method's ranked doc_ids, for evals/retrieval_eval.py's ablation
    across BM25 / dense / hybrid / hybrid+rerank (docs/DESIGN.md section 12).
    `method`: "bm25" | "dense" | "hybrid" | "hybrid_rerank"."""
    with traced_span("rag.retrieve_ablation", input=query, metadata={"method": method}) as span:
        result = await _retrieve_ablation_impl(
            session, query, method, embedder=embedder, reranker=reranker, doc_type=doc_type, top_k=top_k
        )
        if span is not None:
            span.update(output=result)
        return result


async def _retrieve_ablation_impl(
    session: AsyncSession,
    query: str,
    method: str,
    *,
    embedder: Embedder | None,
    reranker: Reranker | None,
    doc_type: str | None,
    top_k: int,
) -> list[str]:
    corpus = await _load_corpus(session, doc_type, None)
    if not corpus:
        return []
    by_id = {d.doc_id: d for d in corpus}

    bm25_index = Bm25Index.from_documents([(d.doc_id, d.text) for d in corpus])
    bm25_ranked = [h.doc_id for h in bm25_index.search(query, TOP_K_PER_METHOD)]
    if method == "bm25":
        return bm25_ranked[:top_k]

    dense_ranked: list[str] = []
    if embedder is not None:
        dense_ranked = [h.doc_id for h in await dense_search(session, embedder(query), TOP_K_PER_METHOD, doc_type)]
    if method == "dense":
        return dense_ranked[:top_k]

    fused = [doc_id for doc_id, _score in rrf_fuse([lst for lst in (bm25_ranked, dense_ranked) if lst])]
    if method == "hybrid":
        return fused[:top_k]

    if method == "hybrid_rerank":
        if reranker is None or not fused:
            return fused[:top_k]
        reranked = reranker(query, [(doc_id, by_id[doc_id].text) for doc_id in fused[:TOP_K_PER_METHOD]])
        return [doc_id for doc_id, _score in reranked[:top_k]]

    raise ValueError(f"unknown method {method!r}")


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    doc_type: str | None = None,
    nationality: str | None = None,
    rewrite_fn: Callable[[str], str] = _default_rewrite,
) -> RetrievalResult:
    with traced_span("rag.retrieve", as_type="retriever", input=query) as span:
        result = await _retrieve_impl(
            session, query, embedder=embedder, reranker=reranker, doc_type=doc_type,
            nationality=nationality, rewrite_fn=rewrite_fn,
        )
        if span is not None:
            span.update(output=[d.doc_id for d in result.docs], metadata={"method": result.method})
        return result


async def _retrieve_impl(
    session: AsyncSession,
    query: str,
    *,
    embedder: Embedder | None,
    reranker: Reranker | None,
    doc_type: str | None,
    nationality: str | None,
    rewrite_fn: Callable[[str], str],
) -> RetrievalResult:
    docs = await _single_pass(session, query, embedder, reranker, doc_type, nationality)
    top_score = docs[0].score if docs else float("-inf")

    if docs and top_score >= RELEVANCE_THRESHOLD:
        return RetrievalResult(docs=docs, low_relevance=False, rewritten_query=None, method="hybrid_rerank")

    rewritten = rewrite_fn(query)
    retry_docs = await _single_pass(session, rewritten, embedder, reranker, doc_type, nationality)
    retry_top_score = retry_docs[0].score if retry_docs else float("-inf")

    if retry_docs and retry_top_score >= RELEVANCE_THRESHOLD:
        return RetrievalResult(
            docs=retry_docs, low_relevance=False, rewritten_query=rewritten, method="rewrite_retry"
        )

    best_docs = retry_docs if retry_top_score > top_score else docs
    return RetrievalResult(docs=best_docs, low_relevance=True, rewritten_query=rewritten, method="fallback")
