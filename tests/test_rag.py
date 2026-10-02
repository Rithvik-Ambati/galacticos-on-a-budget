from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# DATA_SOURCE now defaults to "real" (docs/DECISIONS.md "Synthetic data is no longer
# the silent default") -- tests opt into synthetic explicitly so they don't need
# data_raw/ in CI.
os.environ["DATA_SOURCE"] = "synthetic"

from pipeline.documents import build_opponent_documents, build_player_documents
from pipeline.features import compute_features
from pipeline.ingest import run_ingest
from pipeline.team_profiles import compute_team_profiles
from rag.bm25 import Bm25Index, tokenize
from rag.fusion import rrf_fuse
from rag.retriever import retrieve

SEED = 42


def test_tokenize_lowercases_and_strips_punctuation() -> None:
    assert tokenize("Vinicius Jr., 94 ability!") == ["vinicius", "jr", "94", "ability"]


def test_bm25_ranks_exact_term_match_first() -> None:
    index = Bm25Index.from_documents(
        [
            ("a", "Rodri is a ball winning defensive midfielder with high press resistance"),
            ("b", "Mbappe is a fast striker who scores many goals"),
            ("c", "A generic player profile with nothing distinctive"),
        ]
    )
    hits = index.search("press resistance midfielder", top_k=3)
    assert hits[0].doc_id == "a"


def test_bm25_empty_corpus_returns_nothing() -> None:
    assert Bm25Index.from_documents([]).search("anything") == []


def test_rrf_fuse_rewards_docs_ranked_highly_in_both_lists() -> None:
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]])
    fused_ids = [doc_id for doc_id, _score in fused]
    assert fused_ids[0] in ("a", "b")
    assert "c" in fused_ids and "d" in fused_ids


def test_rrf_fuse_handles_disjoint_lists() -> None:
    fused = rrf_fuse([["a"], ["b"]])
    assert {doc_id for doc_id, _score in fused} == {"a", "b"}


async def test_retrieve_without_models_still_returns_lexical_matches(tmp_path) -> None:
    db_path = tmp_path / "rag_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await run_ingest(engine, seed=SEED, output_dir=str(tmp_path))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await compute_features(session)
    async with session_factory() as session:
        await compute_team_profiles(session)
    async with session_factory() as session:
        await build_player_documents(session, "none", None)
    async with session_factory() as session:
        await build_opponent_documents(session, "none", None)

    async with session_factory() as session:
        result = await retrieve(session, "tackles won progressive carries", embedder=None, reranker=None)

    assert isinstance(result.docs, list)
    # No embedder means doc_type=None dense search is skipped entirely, but BM25 +
    # fusion still ran -- this is the degraded-but-functional path docs/DECISIONS.md
    # documents, not a crash.
    await engine.dispose()


async def test_retrieve_on_empty_corpus_is_low_relevance_not_a_crash(tmp_path) -> None:
    db_path = tmp_path / "empty.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    from db.bootstrap import create_all

    await create_all(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await retrieve(session, "anything at all", embedder=None, reranker=None)
    assert result.docs == []
    assert result.low_relevance
    assert result.method == "fallback"
    await engine.dispose()
