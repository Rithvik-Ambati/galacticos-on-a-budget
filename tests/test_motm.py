from __future__ import annotations

from engine.motm import man_of_the_match
from engine.schemas import Lineup, MatchEvent, PlayerCard, SimulationResult


def _card(pid: str, name: str, group: str, code: str, ability: float) -> PlayerCard:
    return PlayerCard(
        player_id=pid, name=name, nationality="ESP", position_group=group,
        position_code=code, ability_score=ability, price_eur=1_000_000,
    )


def _lineup() -> Lineup:
    players = {
        "GK": _card("gk", "Keeper", "GK", "GK", 70),
        "LB": _card("lb", "Lefty", "DF", "LB", 60),
        "CB1": _card("cb1", "Rock", "DF", "CB", 90),  # deliberately the highest ability -> tie-break target
        "CB2": _card("cb2", "Stone", "DF", "CB", 65),
        "RB": _card("rb", "Righty", "DF", "RB", 60),
        "DM": _card("dm", "Pivot", "MF", "DM", 60),
        "LCM": _card("lcm", "Box2box", "MF", "CM", 60),
        "RCM": _card("rcm", "Creator", "MF", "CM", 60),
        "LW": _card("lw", "Winger", "FW", "LW", 60),
        "ST": _card("st", "Striker", "FW", "ST", 60),
        "RW": _card("rw", "Flyer", "FW", "RW", 60),
    }
    return Lineup(formation="4-3-3", assignments=players)


def _sim(
    events: list[MatchEvent],
    score_left_right_center: tuple[float, float, float] = (1 / 3, 1 / 3, 1 / 3),
) -> SimulationResult:
    left, center, right = score_left_right_center
    return SimulationResult(
        win_pct=50.0, draw_pct=0.0, loss_pct=50.0,
        score_distribution={},
        chance_share_by_zone={"left_channel": left, "center_channel": center, "right_channel": right},
        narrative_events=events,
        narrative_score=(
            sum(1 for e in events if e.side == "user" and e.type == "goal"),
            sum(1 for e in events if e.side == "opponent" and e.type == "goal"),
        ),
    )


def test_0_0_still_produces_a_winner_by_ability_tiebreak() -> None:
    lineup = _lineup()
    sim = _sim([])
    result = man_of_the_match(lineup, sim)
    assert result.player_id == "cb1"  # the highest-ability player with zero contribution either way


def test_scorer_is_credited_and_wins() -> None:
    lineup = _lineup()
    sim = _sim([MatchEvent(minute=10, type="goal", side="user", player_name="Striker", player_id="st")])
    result = man_of_the_match(lineup, sim)
    assert result.player_id == "st"
    scorer = next(c for c in result.contributions if c.player_id == "st")
    assert scorer.goals == 1
    assert scorer.score > 0


def test_assist_is_credited_separately_from_the_goal() -> None:
    lineup = _lineup()
    sim = _sim([
        MatchEvent(
            minute=10, type="goal", side="user", player_name="Striker", player_id="st",
            assist_player_id="rw", assist_player_name="Flyer",
        )
    ])
    result = man_of_the_match(lineup, sim)
    assister = next(c for c in result.contributions if c.player_id == "rw")
    scorer = next(c for c in result.contributions if c.player_id == "st")
    assert assister.assists == 1
    assert assister.goals == 0
    assert scorer.goals == 1


def test_conceding_fewer_than_expected_in_a_zone_rewards_its_defenders() -> None:
    lineup = _lineup()
    # Expected (pre-match) 50% of chances from the left; actual: 0 conceded there,
    # all 2 conceded goals came from the right -- the left-back should show a
    # positive defensive contribution, the right-back a negative one.
    events = [
        MatchEvent(minute=20, type="goal", side="opponent", player_name="Opp A", zone="right"),
        MatchEvent(minute=50, type="goal", side="opponent", player_name="Opp B", zone="right"),
    ]
    sim = _sim(events, score_left_right_center=(0.5, 0.0, 0.5))
    result = man_of_the_match(lineup, sim)
    lb = next(c for c in result.contributions if c.player_id == "lb")
    rb = next(c for c in result.contributions if c.player_id == "rb")
    assert lb.defensive_contribution > 0
    assert rb.defensive_contribution < 0


def test_contributions_sorted_by_score_descending() -> None:
    lineup = _lineup()
    sim = _sim([MatchEvent(minute=10, type="goal", side="user", player_name="Striker", player_id="st")])
    result = man_of_the_match(lineup, sim)
    scores = [c.score for c in result.contributions]
    assert scores == sorted(scores, reverse=True)
