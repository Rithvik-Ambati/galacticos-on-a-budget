"""pipeline/real_source.py: `_load_games_team_sets` must capture each WC2026
team's real name directly from games.csv.gz, since national_teams.csv.gz
doesn't cover every FIFA member federation -- 5 real WC2026 teams (Haiti, Cape
Verde, Ivory Coast, Curacao, DR Congo) have no row there at all, confirmed
against the actual data_raw/ export. Without this fallback, generate() drops
them from the drawable pool entirely even though they have full real squads.

`_aggregate_real_stats` must sum each player's season goals/assists/minutes from
exactly the raw appearance rows inside the one-season lookback window, each row
counted once, across every competition the player appeared in (a deliberate
choice, not a bug -- docs/DECISIONS.md "Season stat window shrunk from 440 to
365 days"). The window used to be 440 days, which pulled in ~75 days of the
*previous* season's tail-end fixtures on top of the current one; confirmed
concretely against the real export (Harry Kane's reported 68 goals included 5
from outside the 2025-26 season).
"""

from __future__ import annotations

import csv
import gzip
import os
from datetime import date

from pipeline.real_source import (
    APPEARANCE_LOOKBACK_DAYS,
    DATASET_SNAPSHOT_DATE,
    _aggregate_real_stats,
    _load_games_team_sets,
)
from pipeline.synthetic_source import TmPlayer

GAMES_HEADER = [
    "game_id", "competition_id", "season", "round", "date", "home_club_id", "away_club_id",
    "home_club_goals", "away_club_goals", "home_club_position", "away_club_position",
    "home_club_manager_name", "away_club_manager_name", "stadium", "attendance", "referee", "url",
    "home_club_formation", "away_club_formation", "home_club_name", "away_club_name", "aggregate",
    "competition_type",
]


def _write_games_csv(path: str, rows: list[dict[str, str]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=GAMES_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def _game_row(**overrides: str) -> dict[str, str]:
    row = {k: "" for k in GAMES_HEADER}
    row.update(overrides)
    return row


def test_load_games_team_sets_captures_wc2026_team_names_for_teams_missing_from_national_teams_csv(
    tmp_path,
) -> None:
    rows = [
        _game_row(
            game_id="g1", competition_id="FIWC", season="2025",
            home_club_id="14161", away_club_id="4311",
            home_club_name="Haiti", away_club_name="Cape Verde",
        ),
        _game_row(
            game_id="g2", competition_id="FIWC", season="2025",
            home_club_id="3591", away_club_id="32364",
            home_club_name="Ivory Coast", away_club_name="Curacao",
        ),
        # a UCL game in the same file must not pollute the WC team-name map
        _game_row(
            game_id="g3", competition_id="CL", season="2025",
            home_club_id="999", away_club_id="998",
            home_club_name="Some Club", away_club_name="Other Club",
        ),
    ]
    _write_games_csv(os.path.join(tmp_path, "games.csv.gz"), rows)

    wc_game_ids, wc_team_ids, ucl_game_ids, ucl_club_ids, wc_team_names = _load_games_team_sets(str(tmp_path))

    assert wc_game_ids == {"g1", "g2"}
    assert wc_team_ids == {"14161", "4311", "3591", "32364"}
    assert ucl_game_ids == {"g3"}
    assert ucl_club_ids == {"999", "998"}
    assert wc_team_names == {
        "14161": "Haiti",
        "4311": "Cape Verde",
        "3591": "Ivory Coast",
        "32364": "Curacao",
    }


APPEARANCES_HEADER = [
    "appearance_id", "game_id", "player_id", "player_club_id", "player_current_club_id",
    "date", "player_name", "competition_id", "yellow_cards", "red_cards", "goals",
    "assists", "minutes_played",
]


def _write_appearances_csv(path: str, rows: list[dict[str, str]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=APPEARANCES_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def _appearance_row(**overrides: str) -> dict[str, str]:
    row = {k: "" for k in APPEARANCES_HEADER}
    row.update(yellow_cards="0", red_cards="0", goals="0", assists="0", minutes_played="90")
    row.update(overrides)
    return row


def _tm_player(tm_id: str, name: str) -> TmPlayer:
    return TmPlayer(
        tm_id=tm_id, name=name, dob=date(1995, 1, 1), nationality="England",
        position_group="FW", position_code="ST", preferred_foot="right", height_cm=185,
        club_id="c1", true_quality=80.0, market_value_eur=50_000_000,
    )


def test_aggregate_real_stats_sums_in_window_rows_once_across_competitions(tmp_path) -> None:
    """Two rows inside the one-season window, in two different competitions --
    both must count (the cross-competition sum is a deliberate choice, not a
    bug), each exactly once."""
    one_season_ago = date.fromordinal(DATASET_SNAPSHOT_DATE.toordinal() - 10)
    rows = [
        _appearance_row(
            player_id="p1", player_name="Test Striker", competition_id="GB1",
            date=one_season_ago.isoformat(), goals="2", assists="1", minutes_played="90",
        ),
        _appearance_row(
            player_id="p1", player_name="Test Striker", competition_id="CL",
            date=one_season_ago.isoformat(), goals="1", assists="0", minutes_played="90",
        ),
    ]
    _write_appearances_csv(os.path.join(tmp_path, "appearances.csv.gz"), rows)

    result = _aggregate_real_stats(str(tmp_path), [_tm_player("p1", "Test Striker")], {}, seed=42)

    assert len(result) == 1
    assert result[0].goals == 3  # 2 (GB1) + 1 (CL), each row counted once
    assert result[0].assists == 1
    assert result[0].minutes == 180


def test_aggregate_real_stats_excludes_rows_outside_the_one_season_window(tmp_path) -> None:
    just_inside = date.fromordinal(DATASET_SNAPSHOT_DATE.toordinal() - APPEARANCE_LOOKBACK_DAYS)
    just_outside = date.fromordinal(DATASET_SNAPSHOT_DATE.toordinal() - APPEARANCE_LOOKBACK_DAYS - 1)
    rows = [
        _appearance_row(
            player_id="p1", player_name="Test Striker", competition_id="GB1",
            date=just_inside.isoformat(), goals="5", minutes_played="90",
        ),
        _appearance_row(
            player_id="p1", player_name="Test Striker", competition_id="GB1",
            date=just_outside.isoformat(), goals="100", minutes_played="90",
        ),
    ]
    _write_appearances_csv(os.path.join(tmp_path, "appearances.csv.gz"), rows)

    result = _aggregate_real_stats(str(tmp_path), [_tm_player("p1", "Test Striker")], {}, seed=42)

    assert len(result) == 1
    assert result[0].goals == 5  # the 100-goal row one day outside the window must not count
    assert result[0].minutes == 90
