"""Opponent tactical profile and the zone-threat map matchups.py scores against.

Implements docs/DESIGN.md section 7.4 ("map to the user's player(s) defending that zone").
"""

from __future__ import annotations

import statistics

from config.game import LEAGUE_AVERAGE_ABILITY_SCORE
from engine.schemas import Lineup, OpponentWeakZone, PlayerCard, TeamProfile

PPDA_AGGRESSIVE = 6.0  # a very high press
PPDA_PASSIVE = 14.0  # a low block

_DEFENSIVE_ZONE_BY_POSITION_CODE = {
    "LB": "left", "LWB": "left",
    "CB": "center",
    "RB": "right", "RWB": "right",
}

# attack_channels keys are from the OPPONENT's attacking perspective (their left/right
# flank). A team's right winger runs at the defending side's left flank, so the zone a
# defender worries about is the mirror of the attacker's own side; center stays center.
_MIRROR = {"left": "right", "right": "left", "center": "center"}


def press_intensity(ppda: float) -> float:
    """Lower PPDA -> higher press intensity, scaled to 0-100."""
    span = PPDA_PASSIVE - PPDA_AGGRESSIVE
    raw = (PPDA_PASSIVE - ppda) / span * 100
    return max(0.0, min(100.0, raw))


def _opponent_attacking_zone_strength(opponent_lineup: Lineup) -> dict[str, float]:
    """Average ability of whoever the opponent currently fields in each attacking flank."""
    from engine.zones import slot_defs, zone_average  # local import avoids a cycle

    defs = slot_defs(opponent_lineup.formation)
    return {
        h: zone_average(opponent_lineup, defs, "att", h) or 50.0
        for h in ("left", "center", "right")
    }


def opponent_weak_zone(
    squad: list[PlayerCard], league_average: float = LEAGUE_AVERAGE_ABILITY_SCORE
) -> OpponentWeakZone:
    """Screen 3's "where they're weak": the opponent's own defensive personnel strength
    per horizontal zone (LB/LWB -> left, CB -> center, RB/RWB -> right), compared
    against the league-average ability baseline -- an attacking opportunity for the
    user, the mirror image of zone_threat_map's "threat to the user" measure."""
    by_zone: dict[str, list[float]] = {"left": [], "center": [], "right": []}
    for p in squad:
        zone = _DEFENSIVE_ZONE_BY_POSITION_CODE.get(p.position_code)
        if zone:
            by_zone[zone].append(p.ability_score)

    zone_strengths = {
        zone: round(statistics.mean(scores), 1) if scores else league_average
        for zone, scores in by_zone.items()
    }

    weakest_zone = min(zone_strengths, key=lambda z: zone_strengths[z])
    weakest_value = zone_strengths[weakest_zone]
    below_average = weakest_value < league_average

    if below_average:
        description = (
            f"Their {weakest_zone} defensive zone rates {weakest_value:.0f}, below the "
            f"league average of {league_average:.0f} — an opening to attack."
        )
    else:
        description = (
            f"No clear weakness; their least strong zone is {weakest_zone} "
            f"({weakest_value:.0f} vs league average {league_average:.0f})."
        )

    return OpponentWeakZone(
        has_clear_weakness=below_average,
        horizontal_zone=weakest_zone,
        zone_strength=weakest_value,
        league_average=league_average,
        zone_strengths=zone_strengths,
        description=description,
    )


def zone_threat_map(
    profile: TeamProfile, opponent_lineup: Lineup | None = None
) -> dict[tuple[str, str], float]:
    """Threat the opponent poses in each (vertical_zone, horizontal_zone) the user must defend.

    Only "def" and "mid" verticals are scored: these are the zones the user's own players
    occupy while defending. Attacking zones are the opponent's defensive problem, not ours.

    With `opponent_lineup` given (counter.py passes this), the static tactical baseline
    from `profile.attack_channels` is blended 50/50 with the ability of whichever player
    the opponent currently fields in the mirrored attacking flank — so substituting in a
    sharper winger measurably raises the threat to the zone they attack, which is what
    lets an opponent "counter" actually move the weak zone on the pitch.
    """
    channels = profile.attack_channels
    base = {
        "left": channels.get("left", 33.3),
        "center": channels.get("center", 33.3),
        "right": channels.get("right", 33.3),
    }
    personnel = _opponent_attacking_zone_strength(opponent_lineup) if opponent_lineup else None

    def channel_threat(horizontal: str) -> float:
        mirrored = _MIRROR[horizontal]
        value = base[mirrored]
        if personnel is not None:
            value = 0.5 * value + 0.5 * personnel[mirrored]
        return value

    press = press_intensity(profile.ppda) if profile.ppda else 50.0
    left, center, right = channel_threat("left"), channel_threat("center"), channel_threat("right")

    return {
        ("def", "left"): left,
        ("def", "center"): center,
        ("def", "right"): right,
        ("mid", "left"): 0.5 * press + 0.5 * left,
        ("mid", "center"): press,
        ("mid", "right"): 0.5 * press + 0.5 * right,
    }
