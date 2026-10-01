from __future__ import annotations

from config.game import RATING_WEIGHTS
from engine.demo_fixtures import BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, build_demo_lineup
from engine.optimizer import manager_score
from engine.rating import get_default_rating_model
from engine.team_profile import press_intensity

RATING_MODEL = get_default_rating_model()


def test_rating_weights_sum_to_one() -> None:
    assert abs(sum(RATING_WEIGHTS.values()) - 1.0) < 1e-9


def test_rating_is_bounded_0_to_100() -> None:
    for scenario in ("strong", "weak_leftback", "all_attack"):
        lineup = build_demo_lineup(scenario)
        result = RATING_MODEL.rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
        assert 0.0 <= result.overall <= 100.0
        for value in result.sub_ratings.model_dump().values():
            assert 0.0 <= value <= 100.0


def test_strong_lineup_rates_above_weak_leftback() -> None:
    strong = RATING_MODEL.rate(build_demo_lineup("strong"), BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
    weak = RATING_MODEL.rate(build_demo_lineup("weak_leftback"), BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
    assert strong.sub_ratings.matchup >= weak.sub_ratings.matchup


def test_press_intensity_bounds() -> None:
    assert press_intensity(6.0) == 100.0
    assert press_intensity(14.0) == 0.0
    assert press_intensity(20.0) == 0.0  # clamps, never goes negative


def test_manager_score_is_near_one_for_the_optimal_lineup_itself() -> None:
    # find_optimal_lineup maximises role-fit (DESIGN 7.6's stated proxy objective), not
    # the composite overall rating directly, so this is "very close to 1", not exact.
    from engine.demo_fixtures import CANDIDATE_POOL
    from engine.optimizer import find_optimal_lineup

    best = find_optimal_lineup("4-3-3", CANDIDATE_POOL, opponent_squad_player_ids=set())
    assert best is not None
    result = manager_score(best, BRAZIL_PROFILE, CANDIDATE_POOL, set(), RATING_MODEL)
    assert abs(result.manager_score - 1.0) < 0.02
