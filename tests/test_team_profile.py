from __future__ import annotations

from engine.schemas import PlayerCard
from engine.team_profile import opponent_weak_zone


def _player(code: str, ability: float) -> PlayerCard:
    return PlayerCard(
        player_id=f"{code}_{ability}", name=f"{code} player", nationality="ESP",
        position_group="DF", position_code=code, ability_score=ability, price_eur=1_000_000,
    )


def test_flags_a_genuinely_below_average_zone() -> None:
    squad = [_player("LB", 35.0), _player("CB", 70.0), _player("RB", 65.0)]
    result = opponent_weak_zone(squad)
    assert result.has_clear_weakness
    assert result.horizontal_zone == "left"
    assert result.zone_strength == 35.0
    assert "left" in result.description
    assert "35" in result.description


def test_no_zone_below_average_reports_least_strong_instead() -> None:
    squad = [_player("LB", 55.0), _player("CB", 60.0), _player("RB", 58.0)]
    result = opponent_weak_zone(squad)
    assert not result.has_clear_weakness
    assert result.horizontal_zone == "left"  # 55 is the lowest of the three, still >= 50
    assert "No clear weakness" in result.description


def test_missing_positions_fall_back_to_league_average() -> None:
    # No RB at all in this (malformed) squad -- the zone shouldn't silently vanish or
    # crash, and a missing zone defaulting to exactly league_average is correctly NOT
    # a flagged weakness (50 is not below 50).
    squad = [_player("LB", 80.0), _player("CB", 80.0)]
    result = opponent_weak_zone(squad)
    assert result.zone_strengths["right"] == 50.0
    assert not result.has_clear_weakness
    assert result.horizontal_zone == "right"


def test_wingback_codes_map_to_the_same_wide_zones_as_fullbacks() -> None:
    squad = [_player("LWB", 30.0), _player("CB", 70.0), _player("RWB", 70.0)]
    result = opponent_weak_zone(squad)
    assert result.zone_strengths["left"] == 30.0
    assert result.has_clear_weakness
    assert result.horizontal_zone == "left"


def test_evidence_always_includes_all_three_zones() -> None:
    squad = [_player("LB", 80.0), _player("CB", 80.0), _player("RB", 80.0)]
    result = opponent_weak_zone(squad)
    assert set(result.zone_strengths) == {"left", "center", "right"}
