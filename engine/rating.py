"""Rating v1 and the RatingModel interface Phase 7's v2 swaps into.

Implements docs/DESIGN.md section 7.3 (v1: weighted sub-ratings -> overall /100).
"""

from __future__ import annotations

import statistics
from typing import Protocol

from config.game import FORMATIONS, RATING_WEIGHTS, Slot
from engine.schemas import Lineup, PlayerCard, RatingResult, SubRatings, TeamProfile
from engine.team_profile import zone_threat_map
from engine.zones import slot_defs as _slot_defs
from engine.zones import zone_average as _zone_average

ROLE_TEMPLATE_BY_POSITION: dict[str, tuple[str, ...]] = {
    "CB": ("ball_playing_cb", "stopper_cb"),
    "LB": ("inverted_fb", "overlapping_fb"),
    "RB": ("inverted_fb", "overlapping_fb"),
    "LWB": ("overlapping_fb", "inverted_fb"),
    "RWB": ("overlapping_fb", "inverted_fb"),
    "DM": ("ball_winning_dm", "deep_lying_playmaker"),
    "CM": ("box_to_box", "deep_lying_playmaker"),
    "AM": ("inside_forward", "winger"),
    "LM": ("winger", "inside_forward"),
    "RM": ("winger", "inside_forward"),
    "LW": ("winger", "inside_forward"),
    "RW": ("winger", "inside_forward"),
    "ST": ("poacher", "target_man"),
}


class RatingModel(Protocol):
    """v2 (XGBoost, Phase 7) implements this same interface and is swapped in only if it
    beats v1 on the backtest (docs/DESIGN.md section 7.3)."""

    def rate(
        self, lineup: Lineup, opponent: TeamProfile, opponent_lineup: Lineup | None = None
    ) -> RatingResult: ...


def role_fit_score(position_code: str, player: PlayerCard) -> float:
    templates = ROLE_TEMPLATE_BY_POSITION.get(position_code)
    if not templates or not player.role_fit:
        return player.ability_score
    fits = [player.role_fit[t] for t in templates if t in player.role_fit]
    return max(fits) if fits else player.ability_score


def _role_fit_score(slot_id: str, slot_defs: dict[str, Slot], player: PlayerCard) -> float:
    position_code = slot_defs[slot_id].position_code if slot_id in slot_defs else ""
    return role_fit_score(position_code, player)


class RatingV1:
    def rate(
        self, lineup: Lineup, opponent: TeamProfile, opponent_lineup: Lineup | None = None
    ) -> RatingResult:
        if lineup.formation not in FORMATIONS:
            raise ValueError(f"Unknown formation {lineup.formation!r}")
        slot_defs = _slot_defs(lineup.formation)

        attack = _zone_average(lineup, slot_defs, "att") or 50.0
        midfield_control = _zone_average(lineup, slot_defs, "mid") or 50.0
        defence = _zone_average(lineup, slot_defs, "def") or 50.0

        threats = zone_threat_map(opponent, opponent_lineup)
        mismatches: list[float] = []
        for (vertical, horizontal), threat in threats.items():
            zone_strength = _zone_average(lineup, slot_defs, vertical, horizontal)
            if zone_strength is None:
                zone_strength = 50.0
            mismatches.append((threat / 100.0) * (100.0 - zone_strength))
        matchup = max(0.0, 100.0 - statistics.mean(mismatches)) if mismatches else 50.0

        role_fits = [
            _role_fit_score(slot_id, slot_defs, player)
            for slot_id, player in lineup.assignments.items()
        ]
        cohesion = statistics.mean(role_fits) if role_fits else 50.0

        line_avgs = [defence, midfield_control, attack]
        spread_penalty = statistics.pstdev(line_avgs) * 2.5 if len(line_avgs) > 1 else 0.0
        balance = max(0.0, 100.0 - spread_penalty)

        sub_ratings = SubRatings(
            attack=round(attack, 2),
            midfield_control=round(midfield_control, 2),
            defence=round(defence, 2),
            matchup=round(matchup, 2),
            cohesion=round(cohesion, 2),
            balance=round(balance, 2),
        )

        overall = sum(getattr(sub_ratings, k) * w for k, w in RATING_WEIGHTS.items())
        overall = max(0.0, min(100.0, overall))

        return RatingResult(sub_ratings=sub_ratings, overall=round(overall, 1))


def get_default_rating_model() -> RatingModel:
    return RatingV1()
