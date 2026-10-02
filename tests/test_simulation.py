from __future__ import annotations

import time

from engine.demo_fixtures import BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, build_demo_lineup
from engine.rating import get_default_rating_model
from engine.rules import get_slots
from engine.schemas import DangerPlayer, Lineup, PlayerCard, RatingResult, SubRatings, TeamProfile
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


def _uniform_lineup(ability: float) -> Lineup:
    """A legal 4-3-3 where every player has the same ability_score -- a flat-quality
    stand-in for "worst"/"optimal" lineups, cheap enough to build without a DB."""
    assignments = {
        slot.slot_id: PlayerCard(
            player_id=slot.slot_id, name=slot.slot_id, nationality=f"NAT{i}", position_group=slot.position_group,
            position_code=slot.position_code, ability_score=ability, price_eur=1_000_000,
        )
        for i, slot in enumerate(get_slots("4-3-3"))
    }
    return Lineup(formation="4-3-3", assignments=assignments)


def test_expected_goals_matches_hand_computed_value() -> None:
    # Regression pin for the Phase 6c rebalance (docs/DECISIONS.md "Rating/simulation
    # rebalance, pass 2"): attack/user-matchup weights raised 1.6/0.6 -> 2.0/1.0 so the
    # TRUE optimal lineup (not a heuristic) reaches the 75-85%/55-65% win% targets vs
    # weak/strong opponents, which pass 1's defence/matchup suppression alone didn't
    # reach (optimal lineup topped out at 66.6%/53.1%).
    lam_user, lam_opp = expected_goals(_rating(attack=90.0, defence=90.0, matchup=95.0), _opponent(92.0))
    assert round(lam_user, 4) == round(0.25 + 0.90 * 2.0 + (95.0 - 50.0) / 100.0 * 1.0, 4)
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


def test_optimal_lineup_beats_worst_lineup_against_every_opponent_strength() -> None:
    """Property, not a hardcoded coefficient-specific number (so future tuning can't
    silently break it): a flat-95-ability lineup must out-win a flat-40-ability
    lineup against opponents of every strength, and its win% must fall as the
    opponent gets stronger -- the real-data finding this phase's coefficient changes
    were tuned against (docs/DECISIONS.md "Rating/simulation rebalance, pass 2")."""
    worst, optimal = _uniform_lineup(40.0), _uniform_lineup(95.0)
    opponents = [_opponent(55.0), _opponent(80.0), _opponent(95.0)]  # weak -> mid -> strong

    optimal_wins = []
    for opponent in opponents:
        worst_rating = RATING_MODEL.rate(worst, opponent)
        optimal_rating = RATING_MODEL.rate(optimal, opponent)
        worst_sim = simulate_match(worst_rating, worst, opponent, runs=4000, seed=1)
        optimal_sim = simulate_match(optimal_rating, optimal, opponent, runs=4000, seed=1)
        assert optimal_sim.win_pct > worst_sim.win_pct, (
            opponent.danger_players[0].ability_score, worst_sim.win_pct, optimal_sim.win_pct
        )
        optimal_wins.append(optimal_sim.win_pct)

    assert optimal_wins == sorted(optimal_wins, reverse=True), optimal_wins


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
