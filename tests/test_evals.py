from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# DATA_SOURCE now defaults to "real" (docs/DECISIONS.md "Synthetic data is no longer
# the silent default") -- tests opt into synthetic explicitly so they don't need
# data_raw/ in CI.
os.environ["DATA_SOURCE"] = "synthetic"

from evals.numeric_eval import run_numeric_eval
from evals.retrieval_eval import GoldenQuery, load_golden, run_retrieval_eval
from llm.provider import StubProvider
from pipeline.features import compute_features
from pipeline.ingest import run_ingest
from pipeline.pricing import compute_prices
from pipeline.team_profiles import compute_team_profiles

SEED = 42


async def _seeded_engine(tmp_path):
    db_path = tmp_path / "evals_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await run_ingest(engine, seed=SEED, output_dir=str(tmp_path))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await compute_features(session)
    async with session_factory() as session:
        await compute_prices(session, seed=SEED)
    async with session_factory() as session:
        await compute_team_profiles(session)
    return engine


def test_load_golden_returns_empty_list_for_missing_file() -> None:
    assert load_golden("does/not/exist.jsonl") == []


async def test_numeric_eval_runs_and_passes_with_stub_provider(tmp_path) -> None:
    engine = await _seeded_engine(tmp_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        report = await run_numeric_eval(session, n_samples=3, seed=SEED, provider=StubProvider())

    assert report.n_samples > 0
    assert report.coach_report_pass_rate == 1.0
    assert report.match_report_pass_rate == 1.0
    assert report.fallback_count == 0
    await engine.dispose()


async def test_retrieval_eval_bm25_only_without_embedder(tmp_path) -> None:
    engine = await _seeded_engine(tmp_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    from pipeline.documents import build_opponent_documents, build_player_documents

    async with session_factory() as session:
        await build_player_documents(session, "none", None)
    async with session_factory() as session:
        await build_opponent_documents(session, "none", None)

    from sqlalchemy import select

    from db.models import Document

    async with session_factory() as session:
        some_doc = (await session.execute(select(Document).limit(1))).scalar_one()

    golden = [GoldenQuery(query=some_doc.text[:30], relevant_doc_ids={some_doc.doc_id})]

    async with session_factory() as session:
        report = await run_retrieval_eval(session, golden, embedder=None, reranker=None)

    assert "bm25" in report.by_method
    assert "dense" not in report.by_method  # no embedder given
    assert report.by_method["bm25"].n_queries == 1
    await engine.dispose()
