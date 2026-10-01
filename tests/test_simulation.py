from __future__ import annotations

import time

from engine.demo_fixtures import BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, build_demo_lineup
from engine.rating import get_default_rating_model
from engine.simulation import simulate_match, simulate_two_legs

RATING_MODEL = get_default_rating_model()


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
