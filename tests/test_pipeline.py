from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.game import BUDGET_EUR, PRICE_FLOOR_EUR, SQUAD_SIZE
from db.models import Player, PlayerFeatures, Price, Squad
from pipeline import id_resolution, synthetic_source
from pipeline.features import _group, compute_features
from pipeline.ingest import run_ingest
from pipeline.pricing import compute_prices

SEED = 42


def test_id_resolution_matches_almost_everyone_correctly() -> None:
    world = synthetic_source.generate(seed=SEED)
    matches, unresolved = id_resolution.resolve(world.tm_players, world.understat_players, world.clubs)

    assert len(unresolved) == 0
    claimed = [m.tm_id for m in matches]
    assert len(claimed) == len(set(claimed)), "a tm_id was claimed by more than one understat record"

    correct = sum(
        1
        for m in matches
        for u in world.understat_players
        if u.understat_id == m.understat_id and u.tm_id_for_grading_only == m.tm_id
    )
    accuracy = correct / len(matches)
    assert accuracy >= 0.97, f"id_resolution accuracy {accuracy:.3f} dropped below 0.97"


@pytest.fixture
async def seeded_engine(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await run_ingest(engine, seed=SEED, output_dir=str(tmp_path))
    yield engine
    await engine.dispose()


async def test_ingest_produces_correctly_sized_squads(seeded_engine) -> None:
    session_factory = async_sessionmaker(seeded_engine, expire_on_commit=False)
    async with session_factory() as session:
        rows = (await session.execute(select(Squad.team_id, Squad.player_id))).all()

    sizes: dict[str, int] = {}
    for team_id, _player_id in rows:
        sizes[team_id] = sizes.get(team_id, 0) + 1

    wc_sizes = {k: v for k, v in sizes.items() if k.startswith("nt_")}
    ucl_sizes = {k: v for k, v in sizes.items() if k.startswith("club_")}
    assert len(wc_sizes) == 12
    assert all(v == 23 for v in wc_sizes.values())
    assert len(ucl_sizes) == 10
    assert all(v >= SQUAD_SIZE for v in ucl_sizes.values())


async def test_features_ability_scores_correlate_with_ground_truth(seeded_engine) -> None:
    world = synthetic_source.generate(seed=SEED)
    truth = {p.tm_id: p.true_quality for p in world.tm_players}

    session_factory = async_sessionmaker(seeded_engine, expire_on_commit=False)
    async with session_factory() as session:
        await compute_features(session)
        players = (await session.execute(select(Player))).scalars().all()
        features = {f.player_id: f for f in (await session.execute(select(PlayerFeatures))).scalars().all()}

    for f in features.values():
        assert 0.0 <= f.ability_score <= 100.0
        assert 0.0 <= f.confidence <= 1.0

    xs = np.array([truth[p.player_id] for p in players])
    ys = np.array([features[p.player_id].ability_score for p in players])
    correlation = float(np.corrcoef(xs, ys)[0, 1])
    assert correlation >= 0.6, f"ability_score only correlates {correlation:.2f} with ground truth"

    for group in ("GK", "DF", "MF", "FW"):
        group_players = [p for p in players if _group(p) == group]
        gxs = np.array([truth[p.player_id] for p in group_players])
        gys = np.array([features[p.player_id].ability_score for p in group_players])
        group_corr = float(np.corrcoef(gxs, gys)[0, 1])
        assert group_corr >= 0.5, f"{group} ability_score only correlates {group_corr:.2f}"


async def test_pricing_respects_floor_and_reports_budget_sanity(seeded_engine) -> None:
    session_factory = async_sessionmaker(seeded_engine, expire_on_commit=False)
    async with session_factory() as session:
        await compute_features(session)
    async with session_factory() as session:
        report = await compute_prices(session, seed=SEED)
        prices = (await session.execute(select(Price))).scalars().all()

    assert len(prices) > 0
    assert all(p.price_eur >= PRICE_FLOOR_EUR for p in prices)
    assert all(p.price_eur % PRICE_FLOOR_EUR == 0 for p in prices)  # rounded to EUR 1M

    assert "full_elite_xi_fits_under_budget" in report.budget_sanity
    assert report.mae_eur >= 0
    assert len(report.top_50) <= 50
    assert all(price <= BUDGET_EUR for _name, price in report.top_50)  # a single player never eats the whole budget
