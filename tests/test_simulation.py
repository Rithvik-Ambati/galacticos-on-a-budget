from __future__ import annotations

import time

from engine.demo_fixtures import BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, build_demo_lineup
from engine.rating import get_default_rating_model
from engine.schemas import DangerPlayer, RatingResult, SubRatings, TeamProfile
from engine.simulation import LAMBDA_MAX, LAMBDA_MIN, expected_goals, simulate_match, simulate_two_legs

RATING_MODEL = get_default_rating_model()


def _rating(attack: float, defence: float, matchup: float) -> RatingResult:
    return RatingResult(
        sub_ratings=SubRatings(
            attack=attack, midfield_control=80.0, defence=defence, matchup=matchup, cohesion=80.0, balance=80.0
        ),
        overall=80.0,
    )


def _opponent(danger_ability: float) -> TeamProfile:
    return TeamProfile(
        team_id="t", name="Test", formation="4-2-3-1",
        danger_players=[DangerPlayer(player_id="1", name="A", position_code="ST", ability_score=danger_ability)],
    )


def test_expected_goals_matches_hand_computed_value() -> None:
    # Regression pin for the Phase 6c rebalance (docs/DECISIONS.md): defence/matchup
    # suppression weights raised from 0.6/0.3 to 1.0/0.6 so a lineup that's genuinely
    # strong against a specific opponent visibly suppresses that opponent's own goals,
    # which wasn't true before (a 92+ rating vs a strong opponent capped near 53% win).
    lam_user, lam_opp = expected_goals(_rating(attack=90.0, defence=90.0, matchup=95.0), _opponent(92.0))
    assert round(lam_user, 4) == round(0.25 + 0.90 * 1.6 + (95.0 - 50.0) / 100.0 * 0.6, 4)
    assert round(lam_opp, 4) == round(0.25 + 0.92 * 1.6 - (90.0 - 50.0) / 100.0 * 1.0 - (95.0 - 50.0) / 100.0 * 0.6, 4)


def test_higher_defence_strictly_suppresses_opponent_lambda() -> None:
    _, lam_opp_weak_def = expected_goals(_rating(attack=85.0, defence=50.0, matchup=50.0), _opponent(85.0))
    _, lam_opp_strong_def = expected_goals(_rating(attack=85.0, defence=95.0, matchup=50.0), _opponent(85.0))
    assert lam_opp_strong_def < lam_opp_weak_def


def test_higher_matchup_suppresses_opponent_and_boosts_user() -> None:
    lam_user_low, lam_opp_low = expected_goals(_rating(attack=85.0, defence=50.0, matchup=50.0), _opponent(85.0))
    lam_user_high, lam_opp_high = expected_goals(_rating(attack=85.0, defence=50.0, matchup=97.0), _opponent(85.0))
    assert lam_opp_high < lam_opp_low
    assert lam_user_high > lam_user_low


def test_dominant_lineup_beats_strong_opponent_more_clearly_than_before() -> None:
    """The exact scenario Step 0's diagnosis measured: a near-maximal lineup (defence
    and matchup both ~90+) facing an opponent whose own danger players are comparably
    elite. Before the rebalance this produced lam_user/lam_opp ~= 1.48 (~53% win);
    the rebalanced weights should pull that ratio up meaningfully."""
    lam_user, lam_opp = expected_goals(_rating(attack=92.2, defence=90.9, matchup=95.3), _opponent(92.4))
    assert lam_user / lam_opp > 1.8


def test_expected_goals_always_clamped() -> None:
    lam_user, lam_opp = expected_goals(_rating(attack=0.0, defence=100.0, matchup=100.0), _opponent(0.0))
    assert LAMBDA_MIN <= lam_user <= LAMBDA_MAX
    assert LAMBDA_MIN <= lam_opp <= LAMBDA_MAX
    lam_user, lam_opp = expected_goals(_rating(attack=100.0, defence=0.0, matchup=0.0), _opponent(100.0))
    assert LAMBDA_MIN <= lam_user <= LAMBDA_MAX
    assert LAMBDA_MIN <= lam_opp <= LAMBDA_MAX


def test_probabilities_sum_to_one() -> None:
    lineup = build_demo_lineup("strong")
    rating = RATING_MODEL.rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
    sim = simulate_match(rating, lineup, BRAZIL_PROFILE, opponent_lineup=BRAZIL_OPPONENT_LINEUP, runs=5000)
    total = sim.win_pct + sim.draw_pct + sim.loss_pct
    assert abs(total - 100.0) < 0.2
    assert abs(sum(sim.score_distribution.values()) - 1.0) < 0.01


def test_same_seed_is_identical() -> None:
    lineup = build_demo_lineup("strong")
    rating = RATING_MODEL.rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
    a = simulate_match(rating, lineup, BRAZIL_PROFILE, opponent_lineup=BRAZIL_OPPONENT_LINEUP, runs=3000, seed=7)
    b = simulate_match(rating, lineup, BRAZIL_PROFILE, opponent_lineup=BRAZIL_OPPONENT_LINEUP, runs=3000, seed=7)
    assert a.model_dump() == b.model_dump()


def test_different_seed_can_differ() -> None:
    lineup = build_demo_lineup("strong")
    rating = RATING_MODEL.rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
    a = simulate_match(rating, lineup, BRAZIL_PROFILE, opponent_lineup=BRAZIL_OPPONENT_LINEUP, runs=3000, seed=1)
    b = simulate_match(rating, lineup, BRAZIL_PROFILE, opponent_lineup=BRAZIL_OPPONENT_LINEUP, runs=3000, seed=2)
    assert a.narrative_events != b.narrative_events or a.win_pct != b.win_pct


def _decided(sim) -> bool:
    """A knockout tie "ends in a draw" only if nothing ever broke it. Level on the
    scoreboard after ET is a normal, real part of football (it's exactly when a
    shootout happens) as long as the shootout itself produced a winner."""
    if sim.narrative_score[0] != sim.narrative_score[1]:
        return True
    return bool(sim.went_to_penalties and sim.penalty_score and sim.penalty_score[0] != sim.penalty_score[1])


def test_knockout_single_match_never_ends_level() -> None:
    lineup = build_demo_lineup("strong")
    rating = RATING_MODEL.rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
    for seed in range(15):
        sim = simulate_match(
            rating, lineup, BRAZIL_PROFILE, opponent_lineup=BRAZIL_OPPONENT_LINEUP,
            knockout=True, runs=500, seed=seed,
        )
        assert _decided(sim), sim.model_dump()


def test_two_legs_aggregate_never_ends_level() -> None:
    for seed in range(10):
        sim = simulate_two_legs(
            RATING_MODEL, build_demo_lineup("strong"), BRAZIL_PROFILE,
            opponent_lineup=BRAZIL_OPPONENT_LINEUP, runs=500, seed=seed,
        )
        assert _decided(sim), sim.model_dump()


def test_simulation_runs_within_one_second() -> None:
    lineup = build_demo_lineup("strong")
    rating = RATING_MODEL.rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
    start = time.perf_counter()
    simulate_match(rating, lineup, BRAZIL_PROFILE, opponent_lineup=BRAZIL_OPPONENT_LINEUP, runs=10_000)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"{elapsed:.3f}s exceeds the 1s budget"
