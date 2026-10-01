from __future__ import annotations

from config.game import BUDGET_EUR, NATIONALITY_LIMIT
from engine.rules import eligibility, validate_lineup
from engine.schemas import Lineup, PlayerCard


def card(pid, name="X", nat="ESP", group="DF", code="CB", ability=80, price=20_000_000, **kw) -> PlayerCard:
    return PlayerCard(
        player_id=pid, name=name, nationality=nat, position_group=group,
        position_code=code, ability_score=ability, price_eur=price, **kw,
    )


def full_433_lineup(players: dict[str, PlayerCard]) -> Lineup:
    return Lineup(formation="4-3-3", assignments=players)


def minimal_valid_433() -> dict[str, PlayerCard]:
    return {
        "GK": card("gk", group="GK", code="GK", nat="ESP"),
        "LB": card("lb", group="DF", code="LB", nat="FRA"),
        "CB1": card("cb1", group="DF", code="CB", nat="FRA"),
        "CB2": card("cb2", group="DF", code="CB", nat="BRA"),
        "RB": card("rb", group="DF", code="RB", nat="ARG"),
        "DM": card("dm", group="MF", code="DM", nat="ENG"),
        "LCM": card("lcm", group="MF", code="CM", nat="POR"),
        "RCM": card("rcm", group="MF", code="CM", nat="GER"),
        "LW": card("lw", group="FW", code="LW", nat="ITA"),
        "ST": card("st", group="FW", code="ST", nat="NED"),
        "RW": card("rw", group="FW", code="RW", nat="FRA"),
    }


def test_valid_complete_lineup_passes() -> None:
    lineup = full_433_lineup(minimal_valid_433())
    result = validate_lineup(lineup, opponent_squad_player_ids=set())
    assert result.valid, result.violations
    assert result.filled_slots == 11
    assert result.budget_left_eur == BUDGET_EUR - result.budget_spent_eur


def test_incomplete_lineup_is_invalid_when_required() -> None:
    players = minimal_valid_433()
    del players["RW"]
    lineup = full_433_lineup(players)
    result = validate_lineup(lineup, opponent_squad_player_ids=set())
    assert not result.valid
    assert any(v.code == "incomplete_lineup" for v in result.violations)


def test_incomplete_lineup_allowed_mid_build() -> None:
    players = minimal_valid_433()
    del players["RW"]
    lineup = full_433_lineup(players)
    result = validate_lineup(lineup, opponent_squad_player_ids=set(), require_complete=False)
    assert result.valid
    assert result.filled_slots == 10


def test_budget_exceeded_flagged() -> None:
    players = minimal_valid_433()
    players["ST"] = card("st", group="FW", code="ST", nat="NED", price=BUDGET_EUR)
    lineup = full_433_lineup(players)
    result = validate_lineup(lineup, opponent_squad_player_ids=set())
    assert not result.valid
    assert any(v.code == "budget_exceeded" for v in result.violations)


def test_nationality_limit_exactly_at_cap_is_fine() -> None:
    players = minimal_valid_433()
    players["LB"] = card("lb", group="DF", code="LB", nat="FRA")
    players["CB1"] = card("cb1", group="DF", code="CB", nat="FRA")
    players["RW"] = card("rw", group="FW", code="RW", nat="FRA")
    lineup = full_433_lineup(players)
    result = validate_lineup(lineup, opponent_squad_player_ids=set())
    assert result.valid
    assert result.nationality_counts["FRA"] == NATIONALITY_LIMIT


def test_nationality_limit_exceeded_flagged() -> None:
    players = minimal_valid_433()
    players["LB"] = card("lb", group="DF", code="LB", nat="FRA")
    players["CB1"] = card("cb1", group="DF", code="CB", nat="FRA")
    players["CB2"] = card("cb2", group="DF", code="CB", nat="FRA")
    players["RW"] = card("rw", group="FW", code="RW", nat="FRA")
    lineup = full_433_lineup(players)
    result = validate_lineup(lineup, opponent_squad_player_ids=set())
    assert not result.valid
    assert any(v.code == "nationality_limit" for v in result.violations)


def test_opponent_squad_exclusion_flagged() -> None:
    players = minimal_valid_433()
    lineup = full_433_lineup(players)
    result = validate_lineup(lineup, opponent_squad_player_ids={"st"})
    assert not result.valid
    assert any(v.code == "opponent_squad_exclusion" for v in result.violations)


def test_position_mismatch_flagged() -> None:
    players = minimal_valid_433()
    players["ST"] = card("gk2", group="GK", code="GK", nat="NED")
    lineup = full_433_lineup(players)
    result = validate_lineup(lineup, opponent_squad_player_ids=set())
    assert not result.valid
    assert any(v.code == "position_mismatch" for v in result.violations)


def test_duplicate_player_flagged() -> None:
    players = minimal_valid_433()
    shared = card("dup", group="FW", code="ST", nat="NED")
    players["ST"] = shared
    players["LW"] = PlayerCard(**{**shared.model_dump(), "position_code": "LW"})
    lineup = full_433_lineup(players)
    result = validate_lineup(lineup, opponent_squad_player_ids=set())
    assert not result.valid
    assert any(v.code == "duplicate_player" for v in result.violations)


def test_eligibility_opponent_squad() -> None:
    lineup = full_433_lineup(minimal_valid_433())
    target = card("opp1", group="FW", code="ST", nat="BRA")
    result = eligibility(target, lineup, opponent_squad_player_ids={"opp1"})
    assert not result.eligible
    assert "opponent" in result.reason.lower()


def test_eligibility_nationality_limit() -> None:
    players = minimal_valid_433()
    players["LB"] = card("lb", group="DF", code="LB", nat="FRA")
    players["CB1"] = card("cb1", group="DF", code="CB", nat="FRA")
    players["RW"] = card("rw", group="FW", code="RW", nat="FRA")
    lineup = full_433_lineup(players)
    target = card("newfra", group="MF", code="DM", nat="FRA")
    result = eligibility(target, lineup, opponent_squad_player_ids=set(), slot_id="DM")
    assert not result.eligible
    assert "limit" in result.reason.lower()


def test_eligibility_same_nationality_replacement_allowed() -> None:
    players = minimal_valid_433()
    players["LB"] = card("lb", group="DF", code="LB", nat="FRA")
    players["CB1"] = card("cb1", group="DF", code="CB", nat="FRA")
    players["RW"] = card("rw", group="FW", code="RW", nat="FRA")
    lineup = full_433_lineup(players)
    replacement = card("newfra", group="DF", code="LB", nat="FRA", price=1)
    result = eligibility(replacement, lineup, opponent_squad_player_ids=set(), slot_id="LB")
    assert result.eligible


def test_eligibility_budget() -> None:
    lineup = full_433_lineup(minimal_valid_433())
    too_expensive = card("rich", group="FW", code="ST", nat="BRA", price=BUDGET_EUR)
    result = eligibility(too_expensive, lineup, opponent_squad_player_ids=set(), slot_id="ST")
    assert not result.eligible
    assert "budget" in result.reason.lower() or "left" in result.reason.lower()
