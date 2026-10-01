from __future__ import annotations

from engine.demo_fixtures import BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, build_demo_lineup
from engine.optimizer import manager_score
from engine.rating import get_default_rating_model
from engine.rules import validate_lineup
from engine.schemas import LineupAnalysis
from engine.simulation import simulate_match
from engine.swaps import swaps_by_weakness
from engine.weaknesses import find_weaknesses
from llm.narrator import narrate_coach_report, narrate_match_report
from llm.provider import StubProvider
from llm.sql_tool import ALLOWED_TABLES, ROW_LIMIT, guard_sql
from llm.validator import extract_numbers, validate_and_fix, validate_numbers


def test_extract_numbers_handles_commas_and_percent() -> None:
    assert extract_numbers("Rating 86.4, budget EUR41,000,000, win 58%") == [86.4, 41000000.0, 58.0]


def test_validate_numbers_accepts_within_tolerance() -> None:
    outcome = validate_numbers("The rating is 86.4 and spend is 41,000,500", {86.4, 41_000_000.0})
    assert outcome.passed, outcome.bad_numbers


def test_validate_numbers_rejects_invented_number() -> None:
    outcome = validate_numbers("The rating is 97.2", {86.4})
    assert not outcome.passed
    assert 97.2 in outcome.bad_numbers


def test_validate_and_fix_falls_back_after_two_bad_attempts() -> None:
    result = validate_and_fix(
        "invented 99.9", {10.0}, regenerate=lambda: "still invented 99.9", fallback_text="the safe template"
    )
    assert result.used_fallback
    assert result.text == "the safe template"
    assert result.attempts == 2


def test_validate_and_fix_passes_on_first_try() -> None:
    result = validate_and_fix("rating 10.0", {10.0}, regenerate=lambda: "unused", fallback_text="fallback")
    assert result.passed and not result.used_fallback and result.attempts == 1


def test_sql_tool_rejects_non_select() -> None:
    result = guard_sql("DELETE FROM players")
    assert not result.ok
    assert "SELECT" in result.reason


def test_sql_tool_rejects_disallowed_table() -> None:
    result = guard_sql("SELECT * FROM game_sessions")
    assert not result.ok
    assert "allowlist" in result.reason


def test_sql_tool_rejects_multiple_statements() -> None:
    result = guard_sql("SELECT * FROM players; DROP TABLE players;")
    assert not result.ok


def test_sql_tool_injects_limit_when_missing() -> None:
    result = guard_sql("SELECT name FROM players")
    assert result.ok
    assert f"LIMIT {ROW_LIMIT}" in result.sql


def test_sql_tool_allows_whitelisted_table() -> None:
    assert "players" in ALLOWED_TABLES
    result = guard_sql("SELECT name FROM players LIMIT 5")
    assert result.ok
    assert result.sql == "SELECT name FROM players LIMIT 5"


def _demo_analysis() -> LineupAnalysis:
    lineup = build_demo_lineup("weak_leftback")
    rating_model = get_default_rating_model()
    from engine.demo_fixtures import BRAZIL_SQUAD_IDS, CANDIDATE_POOL

    validation = validate_lineup(lineup, BRAZIL_SQUAD_IDS, require_complete=False)
    rating = rating_model.rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
    weaknesses = find_weaknesses(lineup, BRAZIL_PROFILE)
    swaps = swaps_by_weakness(lineup, BRAZIL_PROFILE, weaknesses, CANDIDATE_POOL, BRAZIL_SQUAD_IDS, rating_model)
    mgr = manager_score(lineup, BRAZIL_PROFILE, CANDIDATE_POOL, BRAZIL_SQUAD_IDS, rating_model)
    sim = simulate_match(rating, lineup, BRAZIL_PROFILE, opponent_lineup=BRAZIL_OPPONENT_LINEUP, runs=500)
    return LineupAnalysis(
        session_id="t", formation=lineup.formation, rating=rating, weaknesses=weaknesses,
        swaps_by_weakness=swaps, manager_score=mgr, validation=validation,
        win_draw_loss=(sim.win_pct, sim.draw_pct, sim.loss_pct),
    )


def test_narrate_coach_report_with_stub_never_fails_validation() -> None:
    analysis = _demo_analysis()
    result = narrate_coach_report(analysis, "Brazil", StubProvider())
    assert result.passed
    assert not result.used_fallback
    assert f"{analysis.rating.overall:.1f}" in result.text


def test_narrate_match_report_with_stub_never_fails_validation() -> None:
    rating_model = get_default_rating_model()
    lineup = build_demo_lineup("weak_leftback")
    rating = rating_model.rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)
    sim = simulate_match(rating, lineup, BRAZIL_PROFILE, opponent_lineup=BRAZIL_OPPONENT_LINEUP, runs=500)
    result = narrate_match_report(sim, "Brazil", StubProvider())
    assert result.passed
    assert str(sim.narrative_score[0]) in result.text
