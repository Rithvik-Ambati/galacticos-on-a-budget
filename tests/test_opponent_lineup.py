"""Part 2b (docs/DECISIONS.md "Thin squads"): the opponent must always field
exactly 11 players in a valid formation, filling thin position groups from the
nearest adjacent group rather than leaving a slot empty.
"""

from __future__ import annotations

import os

os.environ["DATA_SOURCE"] = "synthetic"

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.game import OPPONENT_FORMATION_SLOTS
from db.models import Club, NationalTeam
from engine.opponent_lineup import build_opponent_lineup
from engine.schemas import PlayerCard
from pipeline.features import compute_features
from pipeline.ingest import run_ingest
from pipeline.pricing import compute_prices
from pipeline.team_profiles import compute_team_profiles
from pipeline.to_engine import load_squad_player_cards

SEED = 42


def _card(pid: str, group: str, ability: float = 70.0) -> PlayerCard:
    return PlayerCard(
        player_id=pid, name=pid, nationality="ESP", position_group=group,
        position_code="CB" if group == "DF" else "CM" if group == "MF" else "ST" if group == "FW" else "GK",
        ability_score=ability, price_eur=1_000_000,
    )


def test_fills_a_thin_position_group_from_the_fallback_chain() -> None:
    # Only 2 DF players for 3 DF slots (LB/CB1/CB2/RB need 4) -- the 4th DF slot
    # must fall back to MF.
    squad = [
        _card("gk", "GK"),
        _card("df1", "DF"), _card("df2", "DF"),
        *[_card(f"mf{i}", "MF") for i in range(6)],
        *[_card(f"fw{i}", "FW") for i in range(3)],
    ]
    result = build_opponent_lineup(squad)
    assert result is not None
    assert len(result.assignments) == 11
    assert len(result.out_of_position) >= 1
    assert all(f.natural_group != "DF" for f in result.out_of_position if f.slot_id in ("LB", "CB1", "CB2", "RB"))


def test_returns_none_when_squad_cannot_field_eleven_at_all() -> None:
    squad = [_card("gk", "GK"), _card("df1", "DF"), _card("mf1", "MF")]  # 3 players total
    assert build_opponent_lineup(squad) is None


def test_no_out_of_position_fills_when_squad_has_full_depth() -> None:
    squad = [
        _card("gk", "GK"),
        *[_card(f"df{i}", "DF") for i in range(6)],
        *[_card(f"mf{i}", "MF") for i in range(6)],
        *[_card(f"fw{i}", "FW") for i in range(3)],
    ]
    result = build_opponent_lineup(squad)
    assert result is not None
    assert result.out_of_position == []


async def _seeded_engine(tmp_path):
    db_path = tmp_path / "opponent_lineup_test.db"
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


async def test_every_fieldable_squad_in_both_modes_has_exactly_eleven_valid(tmp_path) -> None:
    """Property test: for every team in WC2026 and UCL2026 that CAN field 11 (the
    ones draw() would actually offer), the built XI has exactly the 11 formation
    slots, each assignment a real squad member, all distinct -- a valid formation,
    not just an 11-length dict."""
    engine = await _seeded_engine(tmp_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        national_ids = (await session.execute(select(NationalTeam.team_id))).scalars().all()
        club_ids = (await session.execute(select(Club.club_id))).scalars().all()

    checked = 0
    excluded = 0
    for team_id in [*national_ids, *club_ids]:
        async with session_factory() as session:
            squad = await load_squad_player_cards(session, team_id)
        result = build_opponent_lineup(squad)
        if result is None:
            excluded += 1
            continue
        checked += 1
        assert set(result.assignments) == set(OPPONENT_FORMATION_SLOTS)
        assert len(set(result.assignments.values())) == 11  # all distinct players
        squad_ids = {p.player_id for p in squad}
        assert all(pid in squad_ids for pid in result.assignments.values())

    assert checked > 0, "expected at least one fieldable squad in the synthetic seed"
