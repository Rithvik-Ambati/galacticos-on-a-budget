from __future__ import annotations

import time

import pytest

from config.game import COUNTER_MAX_ROUNDS
from engine.counter import run_counter_round
from engine.demo_fixtures import (
    BRAZIL_OPPONENT_LINEUP,
    BRAZIL_PROFILE,
    BRAZIL_SQUAD,
    BRAZIL_SQUAD_IDS,
    build_demo_lineup,
)
from engine.rating import get_default_rating_model

RATING_MODEL = get_default_rating_model()


def test_counter_never_fields_a_player_outside_the_squad() -> None:
    lineup = build_demo_lineup("weak_leftback")
    result, new_opp_lineup = run_counter_round(
        1, lineup, BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, BRAZIL_SQUAD, RATING_MODEL
    )
    assert new_opp_lineup.player_ids() <= BRAZIL_SQUAD_IDS


def test_round_cap_enforced() -> None:
    lineup = build_demo_lineup("weak_leftback")
    with pytest.raises(ValueError):
        run_counter_round(
            COUNTER_MAX_ROUNDS + 1, lineup, BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, BRAZIL_SQUAD, RATING_MODEL
        )


def test_counter_is_deterministic() -> None:
    lineup = build_demo_lineup("weak_leftback")
    result_a, opp_a = run_counter_round(
        1, lineup, BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, BRAZIL_SQUAD, RATING_MODEL
    )
    result_b, opp_b = run_counter_round(
        1, lineup, BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, BRAZIL_SQUAD, RATING_MODEL
    )
    assert result_a.model_dump() == result_b.model_dump()
    assert opp_a.model_dump() == opp_b.model_dump()


def test_three_rounds_run_within_cap_and_fast() -> None:
    lineup = build_demo_lineup("weak_leftback")
    current = BRAZIL_OPPONENT_LINEUP
    start = time.perf_counter()
    for round_number in range(1, COUNTER_MAX_ROUNDS + 1):
        result, current = run_counter_round(
            round_number, lineup, current, BRAZIL_PROFILE, BRAZIL_SQUAD, RATING_MODEL
        )
        assert result.round_number == round_number
        assert current.player_ids() <= BRAZIL_SQUAD_IDS
    elapsed_per_round = (time.perf_counter() - start) / COUNTER_MAX_ROUNDS
    assert elapsed_per_round < 1.0, f"{elapsed_per_round:.3f}s/round exceeds the 1s budget"
