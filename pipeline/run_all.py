"""`make pipeline` entry point: ingest -> features -> pricing -> data-quality report."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from config.settings import get_settings
from db.session import get_engine
from pipeline.data_quality import build_report
from pipeline.documents import build_opponent_documents, build_player_documents
from pipeline.features import compute_features
from pipeline.ingest import run_ingest
from pipeline.pricing import compute_prices
from pipeline.team_profiles import compute_team_profiles


async def main() -> None:
    engine = get_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    summary = await run_ingest(engine)
    print(
        f"Ingested {summary.player_count} players, {summary.club_count} clubs, "
        f"{summary.national_team_count} national teams, {summary.squad_rows} squad rows. "
        f"ID resolution: {summary.matched_count} matched, {summary.unresolved_count} unresolved "
        f"(see {summary.unresolved_csv_path})."
    )

    async with session_factory() as session:
        n_features = await compute_features(session)
    print(f"Computed features for {n_features} players.")

    async with session_factory() as session:
        pricing_report = await compute_prices(session)
    print(f"Pricing MAE: EUR{pricing_report.mae_eur:,.0f} ({pricing_report.mae_pct_of_mean:.1f}% of mean).")
    print(f"Budget sanity check: {pricing_report.budget_sanity}")

    async with session_factory() as session:
        n_teams = await compute_team_profiles(session)
    print(f"Computed {n_teams} team profiles.")

    try:
        from rag.embeddings import get_embedder

        embedder = get_embedder()
        embed_model = get_settings().embedding_model
    except Exception as exc:  # pragma: no cover - environment-dependent
        print(f"Embedding model unavailable ({exc}); documents will be stored without embeddings.")
        embedder, embed_model = None, "none"

    async with session_factory() as session:
        n_player_docs = await build_player_documents(session, embed_model, embedder)
    async with session_factory() as session:
        n_opponent_docs = await build_opponent_documents(session, embed_model, embedder)
    print(f"Built {n_player_docs} player documents and {n_opponent_docs} opponent documents.")

    async with session_factory() as session:
        dq_report = await build_report(session)
    print()
    print(dq_report.render())


if __name__ == "__main__":
    asyncio.run(main())
