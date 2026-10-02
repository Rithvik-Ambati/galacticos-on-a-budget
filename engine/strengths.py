"""The strengths catalogue -- the positive mirror of engine/weaknesses.py. Same
contract: every rule returns zero or more Strength objects, each with a type, zone,
severity in [0, 1] and the evidence stats behind it (CLAUDE.md: numbers always come
from engine/, never invented by the LLM).
"""

from __future__ import annotations

from config.game import STRENGTH_THRESHOLDS, STRENGTH_TOP_K
from engine.matchups import zone_mismatches
from engine.rating import role_fit_score
from engine.schemas import Lineup, Strength, TeamProfile
from engine.zones import slot_defs


def _zone_advantage_strengths(lineup: Lineup, opponent: TeamProfile) -> list[Strength]:
    """Mirrors _zone_mismatch_weaknesses: defensive zones where the user's cover
    comfortably beats the opponent's threat there, instead of losing to it."""
    threshold = STRENGTH_THRESHOLDS["zone_advantage"]
    out: list[Strength] = []
    for m in zone_mismatches(lineup, opponent):
        if m.vertical_zone != "def" or not m.affected_slots:
            continue
        advantage = m.zone_strength - m.threat
        if advantage <= threshold:
            continue
        out.append(
            Strength(
                type="zone_advantage",
                vertical_zone=m.vertical_zone,
                horizontal_zone=m.horizontal_zone,
                severity=round(min(1.0, advantage / 50.0), 2),
                evidence={"threat": m.threat, "zone_strength": m.zone_strength},
                affected_slots=m.affected_slots,
                description=(
                    f"Your {m.zone_strength:.0f}-rated {m.horizontal_zone} defence comfortably "
                    f"covers their {m.threat:.0f} threat there."
                ),
            )
        )
    return out


def _matchup_win_strengths(lineup: Lineup, opponent: TeamProfile) -> list[Strength]:
    """Mirrors _press_resistance_weakness's zone (mid), flipped: midfield zones where
    the user's cover clearly beats the opponent's (press-adjusted) threat."""
    threshold = STRENGTH_THRESHOLDS["zone_advantage"]
    out: list[Strength] = []
    for m in zone_mismatches(lineup, opponent):
        if m.vertical_zone != "mid" or not m.affected_slots:
            continue
        advantage = m.zone_strength - m.threat
        if advantage <= threshold:
            continue
        out.append(
            Strength(
                type="matchup_win",
                vertical_zone=m.vertical_zone,
                horizontal_zone=m.horizontal_zone,
                severity=round(min(1.0, advantage / 50.0), 2),
                evidence={"threat": m.threat, "zone_strength": m.zone_strength},
                affected_slots=m.affected_slots,
                description=(
                    f"Your midfield will control the ball through the {m.horizontal_zone} "
                    f"channel ({m.zone_strength:.0f} vs their {m.threat:.0f})."
                ),
            )
        )
    return out


def _role_coverage_strengths(lineup: Lineup) -> list[Strength]:
    """A player exceptionally well suited to their specific tactical role, mirroring
    _missing_role_weakness's role-fit check but for "well covered," not "missing."""
    threshold = STRENGTH_THRESHOLDS["role_coverage"]
    defs = slot_defs(lineup.formation)
    out: list[Strength] = []
    for slot_id, player in lineup.assignments.items():
        if slot_id not in defs:
            continue
        fit = role_fit_score(defs[slot_id].position_code, player)
        if fit < threshold:
            continue
        out.append(
            Strength(
                type="role_coverage",
                vertical_zone=defs[slot_id].vertical_zone,
                horizontal_zone=defs[slot_id].horizontal_zone,
                severity=round(min(1.0, (fit - threshold) / (100.0 - threshold) + 0.5), 2),
                evidence={"role_fit": round(fit, 1)},
                affected_slots=[slot_id],
                description=f"{player.name} is an excellent fit for the {defs[slot_id].position_code} role ({fit:.0f}).",
            )
        )
    return out


def find_strengths(lineup: Lineup, opponent: TeamProfile) -> list[Strength]:
    strengths = (
        _zone_advantage_strengths(lineup, opponent)
        + _matchup_win_strengths(lineup, opponent)
        + _role_coverage_strengths(lineup)
    )
    strengths.sort(key=lambda s: s.severity, reverse=True)
    return strengths[:STRENGTH_TOP_K]
