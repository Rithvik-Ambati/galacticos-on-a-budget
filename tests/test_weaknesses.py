from __future__ import annotations

from engine.demo_fixtures import BRAZIL_PROFILE, build_demo_lineup
from engine.weaknesses import find_weaknesses


def test_weak_leftback_scenario_flags_zone_mismatch() -> None:
    lineup = build_demo_lineup("weak_leftback")
    weaknesses = find_weaknesses(lineup, BRAZIL_PROFILE)
    zone_mismatches = [w for w in weaknesses if w.type == "zone_mismatch"]
    assert zone_mismatches, "expected a zone mismatch on the weak left-back"
    assert zone_mismatches[0].horizontal_zone == "left"
    assert "LB" in zone_mismatches[0].affected_slots


def test_strong_scenario_has_no_leftback_mismatch() -> None:
    lineup = build_demo_lineup("strong")
    weaknesses = find_weaknesses(lineup, BRAZIL_PROFILE)
    left_def_mismatches = [
        w for w in weaknesses if w.type == "zone_mismatch" and w.horizontal_zone == "left"
    ]
    assert left_def_mismatches == []


def test_all_attack_scenario_flags_press_resistance() -> None:
    lineup = build_demo_lineup("all_attack")
    weaknesses = find_weaknesses(lineup, BRAZIL_PROFILE)
    assert any(w.type == "low_press_resistance" for w in weaknesses)


def test_weaknesses_sorted_by_severity_descending() -> None:
    lineup = build_demo_lineup("all_attack")
    weaknesses = find_weaknesses(lineup, BRAZIL_PROFILE)
    severities = [w.severity for w in weaknesses]
    assert severities == sorted(severities, reverse=True)


def test_every_weakness_has_evidence_or_explicit_empty_dict() -> None:
    for scenario in ("strong", "weak_leftback", "all_attack"):
        lineup = build_demo_lineup(scenario)
        for w in find_weaknesses(lineup, BRAZIL_PROFILE):
            assert isinstance(w.evidence, dict)
            assert 0.0 <= w.severity <= 1.0
