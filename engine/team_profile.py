"""Opponent tactical profile and the zone-threat map matchups.py scores against.

Implements docs/DESIGN.md section 7.4 ("map to the user's player(s) defending that zone").
"""

from __future__ import annotations

from engine.schemas import Lineup, TeamProfile

PPDA_AGGRESSIVE = 6.0  # a very high press
PPDA_PASSIVE = 14.0  # a low block

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
