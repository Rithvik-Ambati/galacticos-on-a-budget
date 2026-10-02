"""Man of the match: per-player match contribution from the same simulated run shown
on the match-day timeline. Goals and assists are discrete per-event credit;
defensive contribution compares each defensive zone's actual conceded goals against
the pre-match expected share of the opponent's chances in that zone (the same
chance_share_by_zone the scouting/match report already shows) -- a zone that concedes
fewer goals than its pre-match expectation implies was well defended, not just
"nobody scored on them by luck." Always produces a winner, including 0-0, by
tie-breaking on ability score (CLAUDE.md: numbers always come from engine/).
"""

from __future__ import annotations

from collections import Counter

from config.game import MOTM_ASSIST_WEIGHT, MOTM_DEFENSIVE_WEIGHT, MOTM_GOAL_WEIGHT
from engine.schemas import Lineup, ManOfTheMatch, PlayerContribution, SimulationResult
from engine.zones import slot_defs


def man_of_the_match(lineup: Lineup, sim: SimulationResult) -> ManOfTheMatch:
    defs = slot_defs(lineup.formation)

    contributions: dict[str, PlayerContribution] = {
        p.player_id: PlayerContribution(player_id=p.player_id, player_name=p.name, ability_score=p.ability_score)
        for p in lineup.assignments.values()
    }

    for event in sim.narrative_events:
        if event.type != "goal":
            continue
        if event.side == "user" and event.player_id in contributions:
            contributions[event.player_id].goals += 1
            if event.assist_player_id and event.assist_player_id in contributions:
                contributions[event.assist_player_id].assists += 1

    opponent_goals_by_zone = Counter(
        e.zone for e in sim.narrative_events if e.side == "opponent" and e.type == "goal" and e.zone
    )
    total_conceded = sum(opponent_goals_by_zone.values())
    expected_share = {
        "left": sim.chance_share_by_zone.get("left_channel", 1 / 3),
        "center": sim.chance_share_by_zone.get("center_channel", 1 / 3),
        "right": sim.chance_share_by_zone.get("right_channel", 1 / 3),
    }

    for zone in ("left", "center", "right"):
        expected = expected_share[zone] * total_conceded
        actual = opponent_goals_by_zone.get(zone, 0)
        defensive_delta = expected - actual  # positive = conceded fewer than expected
        zone_slots = [
            sid for sid, s in defs.items() if s.vertical_zone == "def" and s.horizontal_zone == zone
        ]
        for slot_id in zone_slots:
            player = lineup.assignments.get(slot_id)
            if player is not None and player.player_id in contributions:
                contributions[player.player_id].defensive_contribution += defensive_delta

    for c in contributions.values():
        c.defensive_contribution = round(c.defensive_contribution, 2)
        c.score = round(
            c.goals * MOTM_GOAL_WEIGHT + c.assists * MOTM_ASSIST_WEIGHT + c.defensive_contribution * MOTM_DEFENSIVE_WEIGHT,
            2,
        )

    ranked = sorted(contributions.values(), key=lambda c: (c.score, c.ability_score), reverse=True)
    winner = ranked[0]
    return ManOfTheMatch(player_id=winner.player_id, player_name=winner.player_name, contributions=ranked)
