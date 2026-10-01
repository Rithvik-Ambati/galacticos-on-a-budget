"""Property-based tests: no swap or optimizer output ever violates a rule.

Implements the Phase 3 acceptance checklist item verbatim. Hypothesis generates
randomised candidate pools; every single thing these two modules hand back must pass
rules.validate_lineup (CLAUDE.md rule 3: never suggest or accept a rule-breaking lineup).
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.demo_fixtures import BRAZIL_PROFILE
from engine.optimizer import find_optimal_lineup
from engine.rating import get_default_rating_model
from engine.rules import validate_lineup
from engine.schemas import Lineup, PlayerCard, Weakness
from engine.swaps import swaps_for_weakness
from tests.test_rules import card, minimal_valid_433

NATS = ["ESP", "FRA", "BRA", "ARG", "ENG", "GER", "ITA", "POR", "NED", "URU"]

GROUP_CODES = {
    "GK": ["GK"],
    "DF": ["LB", "CB", "RB"],
    "MF": ["DM", "CM"],
    "FW": ["LW", "ST", "RW"],
}


@st.composite
def player_strategy(draw, group: str, index: int) -> PlayerCard:
    code = draw(st.sampled_from(GROUP_CODES[group]))
    nat = draw(st.sampled_from(NATS))
    ability = draw(st.floats(min_value=40, max_value=99))
    price = draw(st.integers(min_value=1_000_000, max_value=80_000_000))
    return card(f"{group}_{index}", nat=nat, group=group, code=code, ability=ability, price=price)


@st.composite
def candidate_pool_strategy(draw) -> list[PlayerCard]:
    pool: list[PlayerCard] = []
    counts = {"GK": draw(st.integers(2, 4)), "DF": draw(st.integers(6, 10)),
              "MF": draw(st.integers(5, 8)), "FW": draw(st.integers(5, 8))}
    idx = 0
    for group, n in counts.items():
        for _ in range(n):
            pool.append(draw(player_strategy(group, idx)))
            idx += 1
    return pool


@given(candidate_pool_strategy())
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_optimizer_never_returns_a_rule_breaking_lineup(pool: list[PlayerCard]) -> None:
    result = find_optimal_lineup("4-3-3", pool, opponent_squad_player_ids=set(), time_limit_seconds=2.0)
    if result is None:
        return  # infeasible pool for this draw -- nothing to check
    validation = validate_lineup(result, opponent_squad_player_ids=set())
    assert validation.valid, validation.violations


@st.composite
def lb_candidate_strategy(draw, index: int) -> PlayerCard:
    nat = draw(st.sampled_from(NATS))
    ability = draw(st.floats(min_value=40, max_value=99))
    price = draw(st.integers(min_value=1_000_000, max_value=400_000_000))
    return card(f"lb_cand_{index}", nat=nat, group="DF", code="LB", ability=ability, price=price)


@given(st.lists(lb_candidate_strategy(0), min_size=0, max_size=25))
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_swaps_never_return_a_rule_breaking_lineup(raw_pool: list[PlayerCard]) -> None:
    # hypothesis reuses the same composite's index=0 for every element; re-key ids so
    # the pool has no duplicate player_id collisions.
    pool = [
        PlayerCard(**{**p.model_dump(), "player_id": f"{p.player_id}_{i}"})
        for i, p in enumerate(raw_pool)
    ]
    lineup = Lineup(formation="4-3-3", assignments=minimal_valid_433())
    weakness = Weakness(
        type="zone_mismatch", vertical_zone="def", horizontal_zone="left",
        severity=0.5, affected_slots=["LB"],
    )
    rating_model = get_default_rating_model()

    suggestions = swaps_for_weakness(
        lineup, BRAZIL_PROFILE, weakness, pool, opponent_squad_player_ids=set(),
        rating_model=rating_model,
    )

    for s in suggestions:
        trial = Lineup(
            formation=lineup.formation,
            assignments={**lineup.assignments, s.out_slot: s.in_player},
        )
        validation = validate_lineup(trial, opponent_squad_player_ids=set(), require_complete=False)
        assert validation.valid, validation.violations
