"""Screen 8's "what worked and what didn't": compares the pre-match weaknesses and
strengths (engine/weaknesses.py, engine/strengths.py) against this match's actual,
simulated chance distribution by zone -- the same zone-tagged opponent goal events
engine/motm.py already uses for defensive contribution. Structured output; the
narrator only phrases it (CLAUDE.md: numbers always come from engine/).
"""

from __future__ import annotations

from collections import Counter

from config.game import POSTMATCH_EXPOSURE_MARGIN_GOALS
from engine.schemas import PostMatchAnalysis, PostMatchItem, SimulationResult, Strength, Weakness

_DEF_ZONES = ("left", "center", "right")


def _zone_conceded_vs_expected(sim: SimulationResult) -> tuple[dict[str, int], dict[str, float]]:
    actual = Counter(
        e.zone for e in sim.narrative_events if e.side == "opponent" and e.type == "goal" and e.zone
    )
    total_conceded = sum(actual.values())
    expected_share = {
        "left": sim.chance_share_by_zone.get("left_channel", 1 / 3),
        "center": sim.chance_share_by_zone.get("center_channel", 1 / 3),
        "right": sim.chance_share_by_zone.get("right_channel", 1 / 3),
    }
    expected = {z: expected_share[z] * total_conceded for z in _DEF_ZONES}
    return {z: actual.get(z, 0) for z in _DEF_ZONES}, expected


def analyse_post_match(
    weaknesses: list[Weakness], strengths: list[Strength], sim: SimulationResult
) -> PostMatchAnalysis:
    actual, expected = _zone_conceded_vs_expected(sim)
    items: list[PostMatchItem] = []

    for w in weaknesses:
        if w.vertical_zone != "def" or w.horizontal_zone not in _DEF_ZONES:
            items.append(
                PostMatchItem(
                    type=w.type, category="weakness", horizontal_zone=w.horizontal_zone, outcome="inconclusive",
                    description=f"{w.description} Not directly measurable from this match's zone-level events.",
                )
            )
            continue
        zone = w.horizontal_zone
        exposed = actual[zone] > expected[zone] + POSTMATCH_EXPOSURE_MARGIN_GOALS
        items.append(
            PostMatchItem(
                type=w.type, category="weakness", horizontal_zone=zone,
                outcome="exposed" if exposed else "held",
                evidence={"actual_conceded": float(actual[zone]), "expected_conceded": round(expected[zone], 2)},
                description=(
                    f"The flagged {zone} weakness was exposed: {actual[zone]} goal(s) conceded there vs "
                    f"{expected[zone]:.1f} expected pre-match."
                    if exposed
                    else f"The {zone} weakness held: only {actual[zone]} goal(s) conceded there "
                    f"(expected {expected[zone]:.1f})."
                ),
            )
        )

    for s in strengths:
        if s.vertical_zone != "def" or s.horizontal_zone not in _DEF_ZONES:
            items.append(
                PostMatchItem(
                    type=s.type, category="strength", horizontal_zone=s.horizontal_zone, outcome="inconclusive",
                    description=f"{s.description} Not directly measurable from this match's zone-level events.",
                )
            )
            continue
        zone = s.horizontal_zone
        breached = actual[zone] > expected[zone] + POSTMATCH_EXPOSURE_MARGIN_GOALS
        items.append(
            PostMatchItem(
                type=s.type, category="strength", horizontal_zone=zone,
                outcome="unexpectedly_breached" if breached else "paid_off",
                evidence={"actual_conceded": float(actual[zone]), "expected_conceded": round(expected[zone], 2)},
                description=(
                    f"The {zone} strength was unexpectedly breached: {actual[zone]} goal(s) conceded there "
                    f"despite the pre-match edge."
                    if breached
                    else f"The {zone} strength paid off: only {actual[zone]} goal(s) conceded there "
                    f"(expected {expected[zone]:.1f})."
                ),
            )
        )

    return PostMatchAnalysis(items=items)
