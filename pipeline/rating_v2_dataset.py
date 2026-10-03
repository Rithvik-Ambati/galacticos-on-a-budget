"""Training data for `engine/rating_v2.py`: real historical matches, turned into
(home zone features, away zone features, goal margin) rows. docs/DECISIONS.md
"Rating v2" / docs/PROGRESS.md Part 6.

Reuses the real Transfermarkt export already in `data_raw/` (`pipeline/real_source.py`
loads from the same files, same `DEFAULT_DATA_DIR`), but spans its *entire* match
history (~89k games back to ~2012), not just the current WC2026/UCL2025-26 season --
rating v2 needs volume, and most of these players' current ability_score is a
reasonable stand-in for their ability at the time of an older match (the project
treats ability as a current-season aggregate everywhere else too, not time-varying;
documented, not hidden).

No real shot-level xG exists in this dataset (`pipeline/real_source.py`'s own
docstring: "xg/xa ... still approximated, since this export has no shot-quality
data") -- the regression target here is the actual **goal margin**, a legitimate,
measured substitute for "expected goals margin," not a guess standing in for one.
"""

from __future__ import annotations

import csv
import gzip
import io
import os
import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PlayerFeatures
from pipeline.real_source import DEFAULT_DATA_DIR, POSITION_CODE_BY_SUB_POSITION

# Same (vertical, horizontal) taxonomy as config.game.Slot/engine.zones.py's
# formation-based zones, keyed by the position_code POSITION_CODE_BY_SUB_POSITION
# already derives from game_lineups.csv.gz's raw "position" string -- matches the
# 4-2-3-1 opponent formation's own AM placement (config/game.py), not guessed.
ZONE_BY_POSITION_CODE: dict[str, tuple[str, str]] = {
    "GK": ("def", "center"),
    "CB": ("def", "center"), "LB": ("def", "left"), "RB": ("def", "right"),
    "DM": ("mid", "center"), "CM": ("mid", "center"), "LM": ("mid", "left"), "RM": ("mid", "right"),
    "AM": ("att", "center"), "LW": ("att", "left"), "RW": ("att", "right"), "ST": ("att", "center"),
}
ZONES: tuple[tuple[str, str], ...] = tuple(
    (v, h) for v in ("def", "mid", "att") for h in ("left", "center", "right")
)
ZONE_FALLBACK_ABILITY = 50.0  # league-average, same fallback engine/rating.py's RatingV1 uses
MIN_COVERED_STARTERS = 6  # per side -- below this, the match's feature vector is too sparse to trust


@dataclass
class MatchExample:
    game_id: str
    home_features: tuple[float, ...]  # 9 zone averages, ZONES order
    away_features: tuple[float, ...]
    goal_margin: int  # home_goals - away_goals
    home_result: int  # 1 win, 0 draw, -1 loss -- for the backtest's Brier score


def _open(data_dir: str, name: str) -> io.TextIOWrapper:
    return gzip.open(os.path.join(data_dir, name), "rt", encoding="utf-8", newline="")


async def _load_ability_map(session: AsyncSession, snapshot: str = "2025-26") -> dict[str, float]:
    rows = (
        await session.execute(
            select(PlayerFeatures.player_id, PlayerFeatures.ability_score).where(
                PlayerFeatures.snapshot == snapshot
            )
        )
    ).all()
    return {player_id: ability for player_id, ability in rows}


def _load_starting_lineups_by_game_club(
    data_dir: str, ability: dict[str, float]
) -> dict[tuple[str, str], list[tuple[str, float]]]:
    """(game_id, club_id) -> [(position_code, ability_score), ...] for starters we
    have an ability score for. Streams the full game_lineups.csv.gz once, keeping
    only rows for players already in `ability` -- cheap, since `ability` only has
    a few thousand entries against the file's ~3.2M rows."""
    by_game_club: dict[tuple[str, str], list[tuple[str, float]]] = {}
    with _open(data_dir, "game_lineups.csv.gz") as f:
        for row in csv.DictReader(f):
            if row["type"] != "starting_lineup":
                continue
            pid = row["player_id"]
            score = ability.get(pid)
            if score is None:
                continue
            code = POSITION_CODE_BY_SUB_POSITION.get(row["position"])
            if code is None:
                continue
            by_game_club.setdefault((row["game_id"], row["club_id"]), []).append((code, score))
    return by_game_club


def _zone_features(starters: list[tuple[str, float]]) -> tuple[float, ...] | None:
    if len(starters) < MIN_COVERED_STARTERS:
        return None
    by_zone: dict[tuple[str, str], list[float]] = {}
    for code, score in starters:
        zone = ZONE_BY_POSITION_CODE.get(code)
        if zone is not None:
            by_zone.setdefault(zone, []).append(score)
    return tuple(
        statistics.mean(by_zone[zone]) if by_zone.get(zone) else ZONE_FALLBACK_ABILITY for zone in ZONES
    )


def _iter_games(data_dir: str) -> csv.DictReader[str]:
    return csv.DictReader(_open(data_dir, "games.csv.gz"))


async def build_training_examples(
    session: AsyncSession, data_dir: str = DEFAULT_DATA_DIR, snapshot: str = "2025-26"
) -> list[MatchExample]:
    if not os.path.exists(os.path.join(data_dir, "games.csv.gz")) or not os.path.exists(
        os.path.join(data_dir, "game_lineups.csv.gz")
    ):
        # CI/synthetic environments never download the 241MB real dataset
        # (same constraint pipeline.download_real_data/weekly-pipeline.yml
        # document) -- an empty result here, not a FileNotFoundError, is the
        # same "skip cleanly" contract every evals/ runner follows.
        return []

    ability = await _load_ability_map(session, snapshot)
    if not ability:
        return []
    by_game_club = _load_starting_lineups_by_game_club(data_dir, ability)

    examples: list[MatchExample] = []
    for row in _iter_games(data_dir):
        if not row["home_club_goals"] or not row["away_club_goals"]:
            continue
        home_starters = by_game_club.get((row["game_id"], row["home_club_id"]))
        away_starters = by_game_club.get((row["game_id"], row["away_club_id"]))
        if home_starters is None or away_starters is None:
            continue
        home_features = _zone_features(home_starters)
        away_features = _zone_features(away_starters)
        if home_features is None or away_features is None:
            continue

        home_goals, away_goals = int(row["home_club_goals"]), int(row["away_club_goals"])
        margin = home_goals - away_goals
        examples.append(
            MatchExample(
                game_id=row["game_id"],
                home_features=home_features,
                away_features=away_features,
                goal_margin=margin,
                home_result=1 if margin > 0 else (-1 if margin < 0 else 0),
            )
        )
    return examples
