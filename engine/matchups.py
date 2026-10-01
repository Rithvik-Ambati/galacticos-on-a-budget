"""Zone mismatch scoring. Implements the first bullet of docs/DESIGN.md section 7.4."""

from __future__ import annotations

import statistics

from pydantic import BaseModel

from config.game import Slot
from engine.schemas import Lineup, PlayerCard, TeamProfile
from engine.team_profile import zone_threat_map
from engine.zones import slot_defs as _slot_defs


def _duel_strength(player: PlayerCard) -> float:
    """What matters for a 1v1 defensive matchup: a specific duel/recovery stat when the
    pipeline has one (docs/DESIGN.md section 7.4: "take-ons & progressive carries vs
    tackles won & dribbled-past rate"), falling back to the general ability score.
    """
    return player.per90.get("duel_strength", player.ability_score)


def _zone_duel_strength(
    lineup: Lineup, defs: dict[str, Slot], vertical: str, horizontal: str
) -> float | None:
    scores = [
        _duel_strength(p)
        for slot_id, p in lineup.assignments.items()
        if slot_id in defs
        and defs[slot_id].vertical_zone == vertical
        and defs[slot_id].horizontal_zone == horizontal
    ]
    return statistics.mean(scores) if scores else None


class ZoneMismatch(BaseModel):
    vertical_zone: str
    horizontal_zone: str
    threat: float
    zone_strength: float
    mismatch_score: float  # 0-100, higher = worse for the user
    affected_slots: list[str]


def zone_mismatches(
    lineup: Lineup, opponent: TeamProfile, opponent_lineup: Lineup | None = None
) -> list[ZoneMismatch]:
    slot_defs = _slot_defs(lineup.formation)
    threats = zone_threat_map(opponent, opponent_lineup)

    results: list[ZoneMismatch] = []
    for (vertical, horizontal), threat in threats.items():
        affected = [
            slot_id
            for slot_id in lineup.assignments
            if slot_id in slot_defs
            and slot_defs[slot_id].vertical_zone == vertical
            and slot_defs[slot_id].horizontal_zone == horizontal
        ]
        zone_strength = _zone_duel_strength(lineup, slot_defs, vertical, horizontal)
        if zone_strength is None:
            zone_strength = 50.0
        mismatch_score = (threat / 100.0) * (100.0 - zone_strength)
        results.append(
            ZoneMismatch(
                vertical_zone=vertical,
                horizontal_zone=horizontal,
                threat=round(threat, 1),
                zone_strength=round(zone_strength, 1),
                mismatch_score=round(mismatch_score, 1),
                affected_slots=affected,
            )
        )
    return sorted(results, key=lambda m: m.mismatch_score, reverse=True)
