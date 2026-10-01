"""Per-90 metrics, position-relative percentiles, ability score, role fit, style vector.

Implements docs/DESIGN.md section 7.1. One season is available in this build (see
docs/DECISIONS.md on the synthetic data), so "last 2 seasons, recency-weighted"
degrades to that single season -- the recency-weighting hook is still there
(`SEASON_RECENCY_WEIGHTS`) for whenever a second season of history exists.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import rankdata
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.game import (
    ABILITY_WEIGHTS,
    FULL_COVERAGE_LOW_MINUTES_CONFIDENCE,
    LOW_COVERAGE_CONFIDENCE,
    LOW_COVERAGE_LEAGUE_STRENGTH,
    MIN_MINUTES_THRESHOLD,
    ROLE_FIT_FORMULAS,
)
from db.models import STYLE_VECTOR_DIM, Player, PlayerFeatures, PlayerStatsSeason

SEASON_RECENCY_WEIGHTS: tuple[float, ...] = (1.0, 0.5)  # most-recent-first, if >1 season exists

PERCENTILE_METRICS = (
    "goals_per90", "assists_per90", "xg_per90", "xa_per90", "shots_per90",
    "key_passes_per90", "tackles_won_per90", "progressive_carries_per90",
    "take_ons_won_per90", "aerial_win_pct", "pass_completion",
)


@dataclass
class RawRow:
    player_id: str
    position_group: str
    minutes: int
    league_strength: float
    per90: dict[str, float]


def _per90(stats: PlayerStatsSeason) -> dict[str, float]:
    scale = 90.0 / stats.minutes if stats.minutes > 0 else 0.0
    aerial_pct = (stats.aerials_won / stats.aerials_total * 100) if stats.aerials_total else 50.0
    return {
        "goals_per90": stats.goals * scale,
        "assists_per90": stats.assists * scale,
        "xg_per90": stats.xg * scale if stats.minutes else 0.0,
        "xa_per90": stats.xa * scale if stats.minutes else 0.0,
        "shots_per90": stats.shots * scale,
        "key_passes_per90": stats.key_passes * scale,
        "tackles_won_per90": stats.tackles_won * scale,
        "dribbled_past_per90": stats.dribbled_past * scale,
        "progressive_carries_per90": stats.progressive_carries * scale,
        "take_ons_won_per90": stats.take_ons_won * scale,
        "aerial_win_pct": aerial_pct,
        "pass_completion": stats.pass_completion,
    }


def compute_role_fit(percentiles: dict[str, float]) -> dict[str, float]:
    """role_percentiles (persisted) -> role fit scores (derived on demand, not stored —
    there's no dedicated column for it; see docs/PROGRESS.md Phase 2 notes)."""
    if not percentiles:
        return {}
    role_fit = {}
    for role, weights in ROLE_FIT_FORMULAS.items():
        total_weight = sum(weights.values())
        score = sum(percentiles.get(key, 50.0) * w for key, w in weights.items()) / total_weight
        role_fit[role] = round(score, 1)
    return role_fit


def _fallback_ability(per90: dict[str, float]) -> float:
    """Low-coverage path: ability from basic appearance numbers only (no percentiles —
    there's no peer group worth ranking against when most peers are also zeroed out)."""
    score = 45.0 + per90["goals_per90"] * 25.0 + per90["assists_per90"] * 18.0
    return round(max(20.0, min(75.0, score)), 1)


async def compute_features(session: AsyncSession, snapshot: str = "2025-26") -> int:
    rows = (await session.execute(select(Player, PlayerStatsSeason).join(PlayerStatsSeason))).all()

    raw_rows: list[RawRow] = []
    for player, stats in rows:
        raw_rows.append(
            RawRow(
                player_id=player.player_id,
                position_group=_group(player),
                minutes=stats.minutes,
                league_strength=stats.league_strength,
                per90=_per90(stats),
            )
        )

    by_group: dict[str, list[RawRow]] = {}
    for r in raw_rows:
        by_group.setdefault(r.position_group, []).append(r)

    percentiles_by_player: dict[str, dict[str, float]] = {}
    for _group_name, group_rows in by_group.items():
        covered = [r for r in group_rows if r.league_strength >= LOW_COVERAGE_LEAGUE_STRENGTH]
        if len(covered) < 2:
            continue
        matrix = {m: np.array([r.per90[m] for r in covered]) for m in PERCENTILE_METRICS}
        ranks = {m: rankdata(matrix[m], method="average") / len(covered) * 100 for m in PERCENTILE_METRICS}
        dribbled_past = np.array([r.per90["dribbled_past_per90"] for r in covered])
        dribbled_rank = rankdata(dribbled_past, method="average") / len(covered) * 100

        for i, r in enumerate(covered):
            pct = {
                f"{m.removesuffix('_per90')}_pct": round(float(ranks[m][i]), 1) for m in PERCENTILE_METRICS
            }
            pct["dribbled_past_pct_inv"] = round(100.0 - float(dribbled_rank[i]), 1)
            percentiles_by_player[r.player_id] = pct

    saved = 0
    for r in raw_rows:
        percentiles = percentiles_by_player.get(r.player_id, {})
        low_coverage = r.league_strength < LOW_COVERAGE_LEAGUE_STRENGTH or not percentiles

        if low_coverage:
            ability_score = _fallback_ability(r.per90)
            confidence = LOW_COVERAGE_CONFIDENCE
        else:
            weights = ABILITY_WEIGHTS.get(r.position_group, ABILITY_WEIGHTS["MF"])
            total_weight = sum(weights.values())
            weighted = sum(percentiles.get(key, 50.0) * w for key, w in weights.items()) / total_weight
            league_factor = 0.9 + 0.1 * min(1.0, r.league_strength)
            ability_score = round(max(0.0, min(100.0, weighted * league_factor)), 1)
            confidence = 1.0 if r.minutes >= MIN_MINUTES_THRESHOLD else FULL_COVERAGE_LOW_MINUTES_CONFIDENCE

        style = [
            percentiles.get(f"{m.removesuffix('_per90')}_pct", 50.0) / 100.0 for m in PERCENTILE_METRICS
        ]
        style = (style + [0.0] * STYLE_VECTOR_DIM)[:STYLE_VECTOR_DIM]

        await session.merge(
            PlayerFeatures(
                player_id=r.player_id,
                snapshot=snapshot,
                role_percentiles=percentiles,
                style_vector=style,
                ability_score=ability_score,
                confidence=confidence,
            )
        )
        saved += 1

    await session.commit()
    return saved


def _group(player: Player) -> str:
    code = player.positions[0] if player.positions else "CM"
    if code == "GK":
        return "GK"
    if code in {"LB", "CB", "RB", "LWB", "RWB"}:
        return "DF"
    if code in {"DM", "CM", "AM", "LM", "RM"}:
        return "MF"
    return "FW"
