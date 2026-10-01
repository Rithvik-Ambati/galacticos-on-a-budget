"""Derives a TeamProfile row for every squad from its players' features.

docs/DESIGN.md's team_profiles table is meant to hold real tactical data (press
intensity, crossing volume, set-piece threat from match events). There's no match
event source in this build (docs/DECISIONS.md), so these are derived heuristically
from the squad's own player features -- documented here, not hidden: a squad heavy
on quick wide attackers gets a higher "crosses_per_match" and left/right emphasis,
a squad with strong tacklers gets a higher press rating, and so on. Swapping in
StatsBomb event data later only touches this module.
"""

from __future__ import annotations

import statistics

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Player, PlayerFeatures, Squad
from db.models import TeamProfile as TeamProfileRow
from engine.team_profile import PPDA_AGGRESSIVE, PPDA_PASSIVE
from pipeline.features import _group


def _avg_ability(rows: list[tuple[Player, PlayerFeatures]]) -> float:
    return statistics.mean(f.ability_score for _p, f in rows) if rows else 50.0


async def compute_team_profiles(session: AsyncSession, snapshot: str = "2026") -> int:
    squad_rows = (await session.execute(select(Squad.team_id, Squad.player_id))).all()
    teams: dict[str, list[str]] = {}
    for team_id, player_id in squad_rows:
        teams.setdefault(team_id, []).append(player_id)

    players_by_id = {p.player_id: p for p in (await session.execute(select(Player))).scalars().all()}
    features_by_id = {f.player_id: f for f in (await session.execute(select(PlayerFeatures))).scalars().all()}

    written = 0
    for team_id, player_ids in teams.items():
        squad = [
            (players_by_id[pid], features_by_id[pid])
            for pid in player_ids
            if pid in players_by_id and pid in features_by_id
        ]
        if not squad:
            continue

        by_code: dict[str, list[tuple[Player, PlayerFeatures]]] = {}
        for p, f in squad:
            by_code.setdefault(p.positions[0] if p.positions else "CM", []).append((p, f))

        left_wide = by_code.get("LW", []) + by_code.get("LB", [])
        right_wide = by_code.get("RW", []) + by_code.get("RB", [])
        center_att = by_code.get("ST", []) + by_code.get("AM", []) + by_code.get("CM", [])
        left_v, right_v, center_v = _avg_ability(left_wide), _avg_ability(right_wide), _avg_ability(center_att)
        total = left_v + right_v + center_v or 1.0
        attack_channels = {
            "left": round(left_v / total * 100, 1),
            "right": round(right_v / total * 100, 1),
            "center": round(center_v / total * 100, 1),
        }

        midfield_defence = [
            (p, f) for p, f in squad if _group(p) in ("MF", "DF")
        ]
        press_proxy = _avg_ability(midfield_defence) / 100.0  # 0-1
        ppda = round(PPDA_PASSIVE - press_proxy * (PPDA_PASSIVE - PPDA_AGGRESSIVE), 2)

        crosses_per_match = round(6 + (left_v + right_v) / 200.0 * 14, 1)

        aerial_candidates = by_code.get("CB", []) + by_code.get("ST", [])
        aerial = round(min(95.0, _avg_ability(aerial_candidates) * 1.05), 1)
        set_piece_threat = round(min(95.0, (aerial + _avg_ability(squad)) / 2), 1)

        top3 = sorted(squad, key=lambda pf: -pf[1].ability_score)[:3]
        danger_players = [
            {
                "player_id": p.player_id,
                "name": p.name,
                "position_code": p.positions[0] if p.positions else "CM",
                "ability_score": f.ability_score,
                "note": f"Ability {f.ability_score:.0f}/100 -- the squad's standout at {p.positions[0]}.",
            }
            for p, f in top3
        ]

        await session.merge(
            TeamProfileRow(
                team_id=team_id,
                snapshot=snapshot,
                attack_channels=attack_channels,
                ppda=ppda,
                crosses_per_match=crosses_per_match,
                set_piece_threat=set_piece_threat,
                aerial=aerial,
                danger_players=danger_players,
            )
        )
        written += 1

    await session.commit()
    return written
