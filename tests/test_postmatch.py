from __future__ import annotations

from engine.postmatch import analyse_post_match
from engine.schemas import MatchEvent, SimulationResult, Strength, Weakness


def _weakness(zone: str) -> Weakness:
    return Weakness(type="zone_mismatch", vertical_zone="def", horizontal_zone=zone, severity=0.5, description="w")


def _strength(zone: str) -> Strength:
    return Strength(type="zone_advantage", vertical_zone="def", horizontal_zone=zone, severity=0.5, description="s")


def _sim(events: list[MatchEvent], shares: tuple[float, float, float] = (1 / 3, 1 / 3, 1 / 3)) -> SimulationResult:
    left, center, right = shares
    return SimulationResult(
        win_pct=50.0, draw_pct=0.0, loss_pct=50.0, score_distribution={},
        chance_share_by_zone={"left_channel": left, "center_channel": center, "right_channel": right},
        narrative_events=events, narrative_score=(0, sum(1 for e in events if e.side == "opponent")),
    )


def test_weakness_marked_exposed_when_conceded_well_above_expected() -> None:
    events = [MatchEvent(minute=i * 10, type="goal", side="opponent", player_name="X", zone="left") for i in range(3)]
    result = analyse_post_match([_weakness("left")], [], _sim(events, shares=(0.2, 0.4, 0.4)))
    assert result.items[0].outcome == "exposed"


def test_weakness_marked_held_when_conceded_at_or_below_expected() -> None:
    result = analyse_post_match([_weakness("left")], [], _sim([]))
    assert result.items[0].outcome == "held"


def test_strength_marked_paid_off_when_zone_concedes_little() -> None:
    result = analyse_post_match([], [_strength("right")], _sim([]))
    assert result.items[0].outcome == "paid_off"


def test_strength_marked_unexpectedly_breached_when_zone_concedes_a_lot() -> None:
    events = [MatchEvent(minute=i * 10, type="goal", side="opponent", player_name="X", zone="right") for i in range(3)]
    result = analyse_post_match([], [_strength("right")], _sim(events, shares=(0.4, 0.4, 0.2)))
    assert result.items[0].outcome == "unexpectedly_breached"


def test_non_def_zone_items_are_inconclusive_not_fabricated() -> None:
    mid_weakness = Weakness(type="low_press_resistance", vertical_zone="mid", horizontal_zone="center", severity=0.5)
    result = analyse_post_match([mid_weakness], [], _sim([]))
    assert result.items[0].outcome == "inconclusive"
