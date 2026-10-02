from __future__ import annotations

from engine.demo_fixtures import BRAZIL_PROFILE, build_demo_lineup
from engine.strengths import find_strengths


def test_strong_scenario_flags_a_zone_advantage() -> None:
    lineup = build_demo_lineup("strong")
    strengths = find_strengths(lineup, BRAZIL_PROFILE)
    assert any(s.type == "zone_advantage" for s in strengths)


def test_never_returns_more_than_the_configured_top_k() -> None:
    for scenario in ("strong", "weak_leftback", "all_attack"):
        lineup = build_demo_lineup(scenario)
        assert len(find_strengths(lineup, BRAZIL_PROFILE)) <= 3


def test_sorted_by_severity_descending() -> None:
    lineup = build_demo_lineup("strong")
    strengths = find_strengths(lineup, BRAZIL_PROFILE)
    severities = [s.severity for s in strengths]
    assert severities == sorted(severities, reverse=True)


def test_every_strength_has_evidence_and_a_valid_severity() -> None:
    for scenario in ("strong", "weak_leftback", "all_attack"):
        lineup = build_demo_lineup(scenario)
        for s in find_strengths(lineup, BRAZIL_PROFILE):
            assert isinstance(s.evidence, dict) and s.evidence
            assert 0.0 <= s.severity <= 1.0
            assert s.description


def test_only_known_strength_types_appear() -> None:
    for scenario in ("strong", "weak_leftback", "all_attack"):
        lineup = build_demo_lineup(scenario)
        for s in find_strengths(lineup, BRAZIL_PROFILE):
            assert s.type in {"zone_advantage", "matchup_win", "role_coverage"}
