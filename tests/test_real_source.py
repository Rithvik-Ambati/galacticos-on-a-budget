"""pipeline/real_source.py: `_load_games_team_sets` must capture each WC2026
team's real name directly from games.csv.gz, since national_teams.csv.gz
doesn't cover every FIFA member federation -- 5 real WC2026 teams (Haiti, Cape
Verde, Ivory Coast, Curacao, DR Congo) have no row there at all, confirmed
against the actual data_raw/ export. Without this fallback, generate() drops
them from the drawable pool entirely even though they have full real squads.
"""

from __future__ import annotations

import csv
import gzip
import os

from pipeline.real_source import _load_games_team_sets

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
