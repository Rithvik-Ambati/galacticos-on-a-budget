"""Data-quality report. Implements the Phase 1 prompt's report script.

Prints: player counts, % with detailed (Understat) stats, % with market value,
squad sizes per team, unresolved ID count.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Player, PlayerStatsSeason, Price, Squad


@dataclass
class DataQualityReport:
    player_count: int
    players_with_stats: int
    players_with_stats_pct: float
    players_with_market_value: int
    players_with_market_value_pct: float
    squad_sizes: dict[str, int]
    unresolved_id_count: int

    def render(self) -> str:
        lines = [
            "# Data quality report",
            "",
            f"- Players: {self.player_count}",
            f"- With detailed (Understat) stats: {self.players_with_stats} "
            f"({self.players_with_stats_pct:.1f}%)",
            f"- With a market value / price row: {self.players_with_market_value} "
            f"({self.players_with_market_value_pct:.1f}%)",
            f"- Unresolved IDs needing manual review: {self.unresolved_id_count}",
            "",
            "## Squad sizes",
        ]
        for team_id, size in sorted(self.squad_sizes.items()):
            flag = "" if size >= 11 else "  <-- UNDER 11, cannot field a lineup"
            lines.append(f"- {team_id}: {size}{flag}")
        return "\n".join(lines)


async def build_report(session: AsyncSession, unresolved_csv_path: str = "data/unresolved_ids.csv") -> DataQualityReport:
    player_count = (await session.execute(select(func.count()).select_from(Player))).scalar_one()

    # "Detailed" means Understat-sourced, not just the basic appearance-stats fallback
    # every player gets (pipeline/ingest.py) -- league_strength >= 0.8 is that signal.
    stats_player_ids = (
        await session.execute(
            select(PlayerStatsSeason.player_id).distinct().where(PlayerStatsSeason.league_strength >= 0.8)
        )
    ).scalars().all()
    players_with_stats = len(set(stats_player_ids))

    price_player_ids = (await session.execute(select(Price.player_id).distinct())).scalars().all()
    players_with_market_value = len(set(price_player_ids))

    squad_rows = (await session.execute(select(Squad.team_id, Squad.player_id))).all()
    squad_sizes: dict[str, int] = {}
    for team_id, _player_id in squad_rows:
        squad_sizes[team_id] = squad_sizes.get(team_id, 0) + 1

    unresolved_id_count = 0
    if os.path.exists(unresolved_csv_path):
        with open(unresolved_csv_path, encoding="utf-8") as f:
            unresolved_id_count = max(0, sum(1 for _ in csv.reader(f)) - 1)

    def pct(n: int) -> float:
        return round(100 * n / player_count, 1) if player_count else 0.0

    return DataQualityReport(
        player_count=player_count,
        players_with_stats=players_with_stats,
        players_with_stats_pct=pct(players_with_stats),
        players_with_market_value=players_with_market_value,
        players_with_market_value_pct=pct(players_with_market_value),
        squad_sizes=squad_sizes,
        unresolved_id_count=unresolved_id_count,
    )
