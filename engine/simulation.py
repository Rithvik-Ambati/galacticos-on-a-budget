"""Poisson Monte Carlo match simulation. Implements docs/DESIGN.md section 7.8.

Expected goals (lambda) come from the rating model's sub-ratings, not from a separately
trained xG model yet — docs/DECISIONS.md flags this as a deliberate v1 simplification;
Phase 7's rating v2 is the documented place a real historical xG-margin model replaces
it, via the same RatingModel interface, without this module changing.
"""

from __future__ import annotations

import statistics

import numpy as np

from config.game import (
    AWAY_DISADVANTAGE_LAMBDA_MULTIPLIER,
    EXTRA_TIME_FRACTION,
    EXTRA_TIME_STAMINA_FACTOR,
    HOME_ADVANTAGE_LAMBDA_MULTIPLIER,
    PENALTY_LEAGUE_AVERAGE_CONVERSION,
    SIMULATION_RUNS,
)
from engine.rating import RatingModel
from engine.schemas import Lineup, MatchEvent, RatingResult, SimulationResult, TeamProfile
from engine.team_profile import zone_threat_map

LAMBDA_MIN = 0.1
LAMBDA_MAX = 4.0


def expected_goals(rating: RatingResult, opponent: TeamProfile) -> tuple[float, float]:
    """(user_lambda, opponent_lambda) in expected goals, from the engine's own numbers only."""
    attack = rating.sub_ratings.attack
    defence = rating.sub_ratings.defence
    matchup = rating.sub_ratings.matchup

    opp_attack_proxy = (
        statistics.mean(dp.ability_score for dp in opponent.danger_players)
        if opponent.danger_players
        else 72.0
    )

    lam_user = 0.25 + (attack / 100.0) * 1.6 + (matchup - 50.0) / 100.0 * 0.6
    lam_opp = (
        0.25
        + (opp_attack_proxy / 100.0) * 1.6
        - (defence - 50.0) / 100.0 * 0.6
        - (matchup - 50.0) / 100.0 * 0.3
    )
    return (
        max(LAMBDA_MIN, min(LAMBDA_MAX, lam_user)),
        max(LAMBDA_MIN, min(LAMBDA_MAX, lam_opp)),
    )


def _chance_share_by_zone(lineup: Lineup, opponent: TeamProfile, opponent_lineup: Lineup | None) -> dict[str, float]:
    threats = zone_threat_map(opponent, opponent_lineup)
    def_threats = {h: threats[("def", h)] for h in ("left", "center", "right")}
    total = sum(def_threats.values()) or 1.0
    return {f"{h}_channel": round(v / total, 3) for h, v in def_threats.items()}


def _simulate_goals(lam_a: float, lam_b: float, runs: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    return rng.poisson(lam_a, size=runs), rng.poisson(lam_b, size=runs)


def _score_distribution(goals_a: np.ndarray, goals_b: np.ndarray) -> dict[str, float]:
    """Full distribution over every scoreline that occurred, so this always sums to 1.0 —
    unlike a top-N truncation, which the Phase 4 acceptance check ("probabilities sum to
    1") would otherwise fail against a long tail of rare scorelines."""
    runs = len(goals_a)
    counts: dict[str, int] = {}
    for ug, og in zip(goals_a, goals_b, strict=False):
        key = f"{int(ug)}-{int(og)}"
        counts[key] = counts.get(key, 0) + 1
    return {
        k: round(v / runs, 4) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
    }


def _penalty_shootout(rng: np.random.Generator, conversion: float = PENALTY_LEAGUE_AVERAGE_CONVERSION) -> tuple[int, int]:
    a, b = 0, 0
    for _ in range(5):
        a += int(rng.random() < conversion)
        b += int(rng.random() < conversion)
    while a == b:
        a += int(rng.random() < conversion)
        b += int(rng.random() < conversion)
    return a, b


def _sample_narrative(
    lam_user: float,
    lam_opp: float,
    user_lineup: Lineup,
    opponent: TeamProfile,
    rng: np.random.Generator,
) -> tuple[list[MatchEvent], tuple[int, int]]:
    attackers = [p for p in user_lineup.assignments.values() if p.position_group in ("FW", "MF")] or list(
        user_lineup.assignments.values()
    )
    weights = np.array([max(1.0, p.ability_score) for p in attackers])
    weights = weights / weights.sum()

    danger = opponent.danger_players or []

    events: list[MatchEvent] = []
    user_goals = int(rng.poisson(lam_user))
    opp_goals = int(rng.poisson(lam_opp))

    for _ in range(user_goals):
        minute = int(rng.integers(1, 91))
        scorer = attackers[int(rng.choice(len(attackers), p=weights))]
        events.append(
            MatchEvent(minute=minute, type="goal", side="user", player_name=scorer.name)
        )
    for _ in range(opp_goals):
        minute = int(rng.integers(1, 91))
        scorer_name = danger[int(rng.integers(0, len(danger)))].name if danger else "Opponent forward"
        events.append(MatchEvent(minute=minute, type="goal", side="opponent", player_name=scorer_name))

    events.sort(key=lambda e: e.minute)
    return events, (user_goals, opp_goals)


def simulate_match(
    rating: RatingResult,
    user_lineup: Lineup,
    opponent: TeamProfile,
    *,
    opponent_lineup: Lineup | None = None,
    knockout: bool = True,
    runs: int = SIMULATION_RUNS,
    seed: int = 42,
) -> SimulationResult:
    """A single match (World Cup mode). `knockout=True` resolves draws via ET + penalties."""
    rng = np.random.default_rng(seed)
    lam_user, lam_opp = expected_goals(rating, opponent)

    user_goals, opp_goals = _simulate_goals(lam_user, lam_opp, runs, rng)
    user_wins = int(np.sum(user_goals > opp_goals))
    draws = int(np.sum(user_goals == opp_goals))
    losses = runs - user_wins - draws

    went_to_et = False
    went_to_pens = False
    penalty_score: tuple[int, int] | None = None

    narrative_events, narrative_score = _sample_narrative(lam_user, lam_opp, user_lineup, opponent, rng)
    if narrative_score[0] == narrative_score[1] and knockout:
        went_to_et = True
        et_lam_user = lam_user * EXTRA_TIME_FRACTION * EXTRA_TIME_STAMINA_FACTOR
        et_lam_opp = lam_opp * EXTRA_TIME_FRACTION * EXTRA_TIME_STAMINA_FACTOR
        et_user = int(rng.poisson(et_lam_user))
        et_opp = int(rng.poisson(et_lam_opp))
        for _g in range(et_user):
            events_minute = 90 + int(rng.integers(1, 31))
            narrative_events.append(
                MatchEvent(minute=events_minute, type="goal", side="user", player_name="ET winner")
            )
        for _g in range(et_opp):
            events_minute = 90 + int(rng.integers(1, 31))
            narrative_events.append(
                MatchEvent(minute=events_minute, type="goal", side="opponent", player_name="ET equaliser")
            )
        narrative_score = (narrative_score[0] + et_user, narrative_score[1] + et_opp)
        narrative_events.sort(key=lambda e: e.minute)

        if narrative_score[0] == narrative_score[1]:
            went_to_pens = True
            penalty_score = _penalty_shootout(rng)
            # a shootout always breaks the tie; the match itself never ends level
            while penalty_score[0] == penalty_score[1]:
                penalty_score = _penalty_shootout(rng)

    score_distribution = _score_distribution(user_goals, opp_goals)

    return SimulationResult(
        win_pct=round(user_wins / runs * 100, 1),
        draw_pct=round(draws / runs * 100, 1),
        loss_pct=round(losses / runs * 100, 1),
        score_distribution=score_distribution,
        chance_share_by_zone=_chance_share_by_zone(user_lineup, opponent, opponent_lineup),
        narrative_events=narrative_events,
        narrative_score=narrative_score,
        went_to_extra_time=went_to_et,
        went_to_penalties=went_to_pens,
        penalty_score=penalty_score,
    )


def simulate_two_legs(
    rating_model: RatingModel,
    user_lineup: Lineup,
    opponent: TeamProfile,
    *,
    opponent_lineup: Lineup | None = None,
    user_is_home_first_leg: bool = True,
    runs: int = SIMULATION_RUNS,
    seed: int = 42,
) -> SimulationResult:
    """Champions League mode: two legs, aggregate score, then ET + penalties in leg two."""
    rng = np.random.default_rng(seed)
    rating = rating_model.rate(user_lineup, opponent, opponent_lineup)
    lam_user, lam_opp = expected_goals(rating, opponent)

    home_mult, away_mult = HOME_ADVANTAGE_LAMBDA_MULTIPLIER, AWAY_DISADVANTAGE_LAMBDA_MULTIPLIER

    if user_is_home_first_leg:
        leg1 = (lam_user * home_mult, lam_opp * away_mult)
        leg2 = (lam_user * away_mult, lam_opp * home_mult)
    else:
        leg1 = (lam_user * away_mult, lam_opp * home_mult)
        leg2 = (lam_user * home_mult, lam_opp * away_mult)

    leg1_user, leg1_opp = _simulate_goals(leg1[0], leg1[1], runs, rng)
    leg2_user, leg2_opp = _simulate_goals(leg2[0], leg2[1], runs, rng)

    agg_user = leg1_user + leg2_user
    agg_opp = leg1_opp + leg2_opp

    user_wins = int(np.sum(agg_user > agg_opp))
    draws = int(np.sum(agg_user == agg_opp))
    losses = runs - user_wins - draws

    narrative_leg1, score_leg1 = _sample_narrative(leg1[0], leg1[1], user_lineup, opponent, rng)
    narrative_leg2_raw, score_leg2 = _sample_narrative(leg2[0], leg2[1], user_lineup, opponent, rng)
    narrative_leg2 = [MatchEvent(**{**e.model_dump(), "minute": e.minute}) for e in narrative_leg2_raw]
    aggregate_score = (score_leg1[0] + score_leg2[0], score_leg1[1] + score_leg2[1])

    went_to_et = False
    went_to_pens = False
    penalty_score: tuple[int, int] | None = None
    if aggregate_score[0] == aggregate_score[1]:
        went_to_et = True
        et_user = int(rng.poisson(lam_user * EXTRA_TIME_FRACTION * EXTRA_TIME_STAMINA_FACTOR))
        et_opp = int(rng.poisson(lam_opp * EXTRA_TIME_FRACTION * EXTRA_TIME_STAMINA_FACTOR))
        aggregate_score = (aggregate_score[0] + et_user, aggregate_score[1] + et_opp)
        if aggregate_score[0] == aggregate_score[1]:
            went_to_pens = True
            penalty_score = _penalty_shootout(rng)
            while penalty_score[0] == penalty_score[1]:
                penalty_score = _penalty_shootout(rng)

    score_distribution = _score_distribution(agg_user, agg_opp)

    return SimulationResult(
        win_pct=round(user_wins / runs * 100, 1),
        draw_pct=round(draws / runs * 100, 1),
        loss_pct=round(losses / runs * 100, 1),
        score_distribution=score_distribution,
        chance_share_by_zone=_chance_share_by_zone(user_lineup, opponent, opponent_lineup),
        narrative_events=narrative_leg1 + narrative_leg2,
        narrative_score=aggregate_score,
        went_to_extra_time=went_to_et,
        went_to_penalties=went_to_pens,
        penalty_score=penalty_score,
    )
