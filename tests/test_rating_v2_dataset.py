"""pipeline/rating_v2_dataset.py: zone-feature computation and the end-to-end
build_training_examples() path against a tiny real-shaped fixture (not the
actual 126MB data_raw/ files -- CI never has those, docs/PROGRESS.md Part 6).
"""

from __future__ import annotations

import csv
import gzip
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Base, PlayerFeatures
from pipeline.rating_v2_dataset import (
    MIN_COVERED_STARTERS,
    ZONE_FALLBACK_ABILITY,
    _zone_features,
    build_training_examples,
)

STYLE_VECTOR_DIM = 16


def test_zone_features_returns_none_below_the_coverage_threshold() -> None:
    starters = [("GK", 80.0)] * (MIN_COVERED_STARTERS - 1)
    assert _zone_features(starters) is None


def test_zone_features_averages_within_a_zone_and_falls_back_for_empty_zones() -> None:
    starters = [
        ("GK", 70.0), ("CB", 80.0), ("CB", 90.0), ("LB", 60.0), ("RB", 60.0),
        ("CM", 50.0), ("ST", 90.0),
    ]
    features = _zone_features(starters)
    assert features is not None

    from pipeline.rating_v2_dataset import ZONES

    by_zone = dict(zip(ZONES, features, strict=True))
    assert by_zone[("def", "center")] == (70.0 + 80.0 + 90.0) / 3  # GK + 2 CB, same zone
    assert by_zone[("def", "left")] == 60.0
    assert by_zone[("def", "right")] == 60.0
    assert by_zone[("mid", "center")] == 50.0
    assert by_zone[("mid", "left")] == ZONE_FALLBACK_ABILITY  # nobody played there
    assert by_zone[("att", "center")] == 90.0


async def test_build_training_examples_returns_empty_without_data_raw_files(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ratingv2.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        examples = await build_training_examples(session, data_dir=str(tmp_path))

    assert examples == []
    await engine.dispose()


def _write_gzip_csv(path: str, rows: list[dict[str, str]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


async def test_build_training_examples_end_to_end_on_a_tiny_fixture(tmp_path) -> None:
    data_dir = str(tmp_path)

    # 7 home starters, 6 away starters -- both >= MIN_COVERED_STARTERS (6).
    home_ids = [f"h{i}" for i in range(7)]
    away_ids = [f"a{i}" for i in range(6)]
    home_positions = ["Goalkeeper", "Centre-Back", "Centre-Back", "Left-Back", "Right-Back",
                       "Central Midfield", "Centre-Forward"]
    away_positions = ["Goalkeeper", "Centre-Back", "Centre-Back", "Left-Back", "Right-Back",
                       "Central Midfield"]

    lineup_rows = []
    for pid, pos in zip(home_ids, home_positions, strict=True):
        lineup_rows.append(
            {"game_lineups_id": f"l_{pid}", "date": "2020-01-01", "game_id": "g1", "player_id": pid,
             "club_id": "home_club", "player_name": pid, "type": "starting_lineup", "position": pos,
             "number": "1", "team_captain": "0"}
        )
    for pid, pos in zip(away_ids, away_positions, strict=True):
        lineup_rows.append(
            {"game_lineups_id": f"l_{pid}", "date": "2020-01-01", "game_id": "g1", "player_id": pid,
             "club_id": "away_club", "player_name": pid, "type": "starting_lineup", "position": pos,
             "number": "1", "team_captain": "0"}
        )
    # a substitute, and a starter with no ability_score row -- neither should count
    lineup_rows.append(
        {"game_lineups_id": "l_sub", "date": "2020-01-01", "game_id": "g1", "player_id": "sub1",
         "club_id": "home_club", "player_name": "sub1", "type": "substitutes", "position": "Centre-Forward",
         "number": "99", "team_captain": "0"}
    )
    lineup_rows.append(
        {"game_lineups_id": "l_unknown", "date": "2020-01-01", "game_id": "g1", "player_id": "unknown_player",
         "club_id": "home_club", "player_name": "unknown_player", "type": "starting_lineup",
         "position": "Centre-Forward", "number": "77", "team_captain": "0"}
    )
    _write_gzip_csv(os.path.join(data_dir, "game_lineups.csv.gz"), lineup_rows)

    games_header = [
        "game_id", "competition_id", "season", "round", "date", "home_club_id", "away_club_id",
        "home_club_goals", "away_club_goals", "home_club_position", "away_club_position",
        "home_club_manager_name", "away_club_manager_name", "stadium", "attendance", "referee", "url",
        "home_club_formation", "away_club_formation", "home_club_name", "away_club_name", "aggregate",
        "competition_type",
    ]
    game_row = {k: "" for k in games_header}
    game_row.update(
        {"game_id": "g1", "home_club_id": "home_club", "away_club_id": "away_club",
         "home_club_goals": "2", "away_club_goals": "0"}
    )
    _write_gzip_csv(os.path.join(data_dir, "games.csv.gz"), [game_row])

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ratingv2.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        for pid in [*home_ids, *away_ids]:
            session.add(
                PlayerFeatures(
                    player_id=pid, snapshot="2025-26", ability_score=70.0,
                    style_vector=[0.0] * STYLE_VECTOR_DIM, role_percentiles={}, confidence=1.0,
                )
            )
        await session.commit()

    async with session_factory() as session:
        examples = await build_training_examples(session, data_dir=data_dir)

    assert len(examples) == 1
    example = examples[0]
    assert example.game_id == "g1"
    assert example.goal_margin == 2
    assert example.home_result == 1
    assert len(example.home_features) == 9
    assert len(example.away_features) == 9
    await engine.dispose()
