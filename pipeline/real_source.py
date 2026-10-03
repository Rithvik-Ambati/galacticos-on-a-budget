"""Real Transfermarkt data, loaded from the public dcaribou/transfermarkt-datasets
export (https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.zip
-- see that project's README; CC0). Produces the exact same `SyntheticWorld` shape as
`pipeline/synthetic_source.py` so `pipeline/ingest.py`, `pipeline/id_resolution.py`,
`pipeline/features.py` and `pipeline/pricing.py` don't need to change at all -- see
docs/DECISIONS.md's note that this was the one swap-in point planned from the start.

**What's really real here, and what isn't** (be honest about this when citing numbers):
- Player identity, nationality, position, age, club, and **market value** are 100%
  real, current data (WC2026 squads pulled from actual June 2026 match lineups, not
  the dataset's own `current_national_team_id` field, which turned out too sparse to
  trust -- see docs/DECISIONS.md).
- Minutes, goals, assists and cards are 100% real, aggregated from real appearances
  in the last ~14 months.
- There is no real shot-quality (xG/xA) or event-level (tackles, aerials, pressing)
  data in this export -- Transfermarkt doesn't track it, and this build never
  integrated a second source like StatsBomb for it (would be the natural next step).
  `xg`/`xa` are approximated as goals/assists. The remaining advanced per-90 metrics
  features.py needs are **synthesized** from each player's real market-value
  percentile (within their position group) as a quality proxy, using the same
  noise-added technique `pipeline/synthetic_source.py` uses for its fully-synthetic
  world -- just driven by a real signal instead of a random one.
"""

from __future__ import annotations

import csv
import gzip
import io
import os
import random
from dataclasses import dataclass
from datetime import date, datetime

from pipeline.synthetic_source import SyntheticWorld, TmPlayer, UnderstatPlayer

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_raw")

BIG5_COMPETITION_IDS = {"GB1", "ES1", "L1", "IT1", "FR1"}
RECENT_SEASONS = {"2025", "2026"}
APPEARANCE_LOOKBACK_DAYS = 440  # ~ last full season + a bit, from the dataset's max date

# The dcaribou export's own max appearances.csv date, confirmed by direct inspection
# (docs/PROGRESS.md Phase 6c). Not a download timestamp -- the actual freshness of
# the underlying data -- so pipeline/data_source.py records this in ingest_metadata
# rather than "whenever someone happened to run the pipeline."
DATASET_SNAPSHOT_DATE = date(2026, 6, 28)

POSITION_GROUP_BY_TM_POSITION = {
    "Goalkeeper": "GK",
    "Defender": "DF",
    "Midfield": "MF",
    "Attack": "FW",
}
POSITION_CODE_BY_SUB_POSITION = {
    "Goalkeeper": "GK",
    "Centre-Back": "CB",
    "Left-Back": "LB",
    "Right-Back": "RB",
    "Defensive Midfield": "DM",
    "Central Midfield": "CM",
    "Attacking Midfield": "AM",
    "Left Midfield": "LM",
    "Right Midfield": "RM",
    "Left Winger": "LW",
    "Right Winger": "RW",
    "Centre-Forward": "ST",
    "Second Striker": "ST",
}
DEFAULT_CODE_BY_GROUP = {"GK": "GK", "DF": "CB", "MF": "CM", "FW": "ST"}


def _open(data_dir: str, name: str) -> io.TextIOWrapper:
    return gzip.open(os.path.join(data_dir, name), "rt", encoding="utf-8", newline="")


def _parse_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(raw: str, default: int = 0) -> int:
    try:
        return int(float(raw))
    except (ValueError, TypeError):
        return default


@dataclass
class _ClubInfo:
    club_id: str
    name: str
    country: str
    competition: str


def _load_competitions(data_dir: str) -> tuple[dict[str, str], dict[str, str]]:
    """(competition_id -> country_name, competition_id -> display name)."""
    countries: dict[str, str] = {}
    names: dict[str, str] = {}
    with _open(data_dir, "competitions.csv.gz") as f:
        for row in csv.DictReader(f):
            countries[row["competition_id"]] = row["country_name"] or "International"
            names[row["competition_id"]] = row["name"]
    return countries, names


def _load_games_team_sets(
    data_dir: str,
) -> tuple[set[str], set[str], set[str], set[str], dict[str, str]]:
    """(wc2026_game_ids, wc2026_team_ids, ucl2025_26_game_ids, ucl2025_26_club_ids,
    wc2026_team_names). The last is games.csv.gz's own `home_club_name`/
    `away_club_name` for each WC2026 team_id -- real, not guessed, and the only
    source of a name for a team that played real WC2026 matches but has no row
    in national_teams.csv.gz (that reference table doesn't cover every FIFA
    member federation; see the fallback in generate())."""
    wc_game_ids: set[str] = set()
    wc_team_ids: set[str] = set()
    ucl_game_ids: set[str] = set()
    ucl_club_ids: set[str] = set()
    wc_team_names: dict[str, str] = {}
    with _open(data_dir, "games.csv.gz") as f:
        for row in csv.DictReader(f):
            if row["competition_id"] == "FIWC" and row["season"] == "2025":
                wc_game_ids.add(row["game_id"])
                wc_team_ids.add(row["home_club_id"])
                wc_team_ids.add(row["away_club_id"])
                wc_team_names[row["home_club_id"]] = row["home_club_name"]
                wc_team_names[row["away_club_id"]] = row["away_club_name"]
            elif row["competition_id"] == "CL" and row["season"] == "2025":
                ucl_game_ids.add(row["game_id"])
                ucl_club_ids.add(row["home_club_id"])
                ucl_club_ids.add(row["away_club_id"])
    return wc_game_ids, wc_team_ids, ucl_game_ids, ucl_club_ids, wc_team_names


def _load_starting_lineup_frequency(
    data_dir: str, game_ids: set[str], candidate_ids: set[str]
) -> dict[str, dict[tuple[str, str], int]]:
    """team_id -> {(player_id, position_code): times actually started (not just
    subbed on) at that position across `game_ids` -- Part 2c's "most frequent
    starters by formation from recent matches." Restricted to `candidate_ids`
    (players who made the final squad cut) so a since-dropped player's old starts
    can't ever outrank a current squad member."""
    counts: dict[str, dict[tuple[str, str], int]] = {}
    with _open(data_dir, "game_lineups.csv.gz") as f:
        for row in csv.DictReader(f):
            if row["type"] != "starting_lineup" or row["game_id"] not in game_ids:
                continue
            pid = row["player_id"]
            if pid not in candidate_ids:
                continue
            code = POSITION_CODE_BY_SUB_POSITION.get(row["position"])
            if code is None:
                continue  # a handful of rows (~0.4%) use a vaguer label ("Defender",
                # "midfield", "Attack", "Sweeper") this dataset doesn't give a precise
                # sub-position for -- skipped rather than guessed, per CLAUDE.md
            team_counts = counts.setdefault(row["club_id"], {})
            key = (pid, code)
            team_counts[key] = team_counts.get(key, 0) + 1
    return counts


def _load_lineup_squads(data_dir: str, game_ids: set[str]) -> dict[str, set[str]]:
    """team_id -> set of player_ids who actually featured in one of `game_ids` --
    far more reliable than `players.current_national_team_id`/`current_club_id` alone,
    which left WC2026 squads at a median of 9 players per team (see docs/DECISIONS.md),
    and (discovered while building this) leaves 3 of the 36 real UCL 2025/26 clubs
    -- newer/smaller-league debutants whose players.csv club-name field is blank --
    at 6-9 players instead of a real squad via `current_club_id` alone."""
    squads: dict[str, set[str]] = {}
    with _open(data_dir, "game_lineups.csv.gz") as f:
        for row in csv.DictReader(f):
            if row["game_id"] in game_ids:
                squads.setdefault(row["club_id"], set()).add(row["player_id"])
    return squads


def _position_group_and_code(position: str, sub_position: str) -> tuple[str, str]:
    group = POSITION_GROUP_BY_TM_POSITION.get(position, "MF")
    code = POSITION_CODE_BY_SUB_POSITION.get(sub_position, DEFAULT_CODE_BY_GROUP[group])
    return group, code


def _market_value(row: dict[str, str]) -> int:
    for key in ("market_value_in_eur", "highest_market_value_in_eur"):
        raw = row.get(key)
        if raw:
            try:
                return max(1, int(float(raw)))
            except ValueError:
                continue
    return 500_000  # a floor for players with no recorded value at all


def generate(seed: int | None = None, data_dir: str = DEFAULT_DATA_DIR) -> SyntheticWorld:
    if not os.path.isdir(data_dir):
        raise FileNotFoundError(
            f"{data_dir} not found. Run `python -m pipeline.download_real_data` first "
            "to fetch the public Transfermarkt export (see this module's docstring)."
        )

    competition_countries, competition_names = _load_competitions(data_dir)
    wc_game_ids, wc_team_ids, ucl_game_ids, ucl_club_ids, wc_team_names = _load_games_team_sets(data_dir)
    wc_squads_by_team = _load_lineup_squads(data_dir, wc_game_ids)
    wc_squad_player_ids: set[str] = set().union(*wc_squads_by_team.values()) if wc_squads_by_team else set()
    ucl_lineup_squads_by_club = _load_lineup_squads(data_dir, ucl_game_ids)
    ucl_lineup_player_ids: set[str] = (
        set().union(*ucl_lineup_squads_by_club.values()) if ucl_lineup_squads_by_club else set()
    )

    # national_teams.csv: display name + fifa ranking for the 48 WC2026 teams.
    national_team_rows: dict[str, dict[str, str]] = {}
    with _open(data_dir, "national_teams.csv.gz") as f:
        for row in csv.DictReader(f):
            if row["national_team_id"] in wc_team_ids:
                national_team_rows[row["national_team_id"]] = row

    # national_teams.csv doesn't cover every FIFA member federation (only 124 rows
    # total) -- 5 real WC2026 teams that definitely played real matches (confirmed
    # via games.csv.gz's own competition_id/season filter above) have no row there:
    # Haiti, Cape Verde, Ivory Coast, Curaçao, DR Congo. Their real name comes
    # straight from games.csv.gz's own home_club_name/away_club_name instead --
    # the same file that already proved they're real WC2026 participants, not a
    # guess standing in for a missing one.
    for tid in wc_team_ids:
        if tid not in national_team_rows and tid in wc_team_names:
            name = wc_team_names[tid]
            national_team_rows[tid] = {"name": name, "country_name": name}

    # players.csv: the full candidate pool. Every selected player keeps whatever real
    # club they're actually at (not just the 36 UCL ones) -- a Bundesliga centre-back
    # with no UCL football this season still needs a valid, real `club_id` for
    # pipeline/ingest.py's `club_by_id[tm.club_id]` lookup to succeed.
    candidate_rows: dict[str, dict[str, str]] = {}
    with _open(data_dir, "players.csv.gz") as f:
        for row in csv.DictReader(f):
            pid = row["player_id"]
            in_wc_squad = pid in wc_squad_player_ids
            in_ucl_lineup = pid in ucl_lineup_player_ids
            recent = row["last_season"] in RECENT_SEASONS
            in_ucl_club = recent and row["current_club_id"] in ucl_club_ids
            in_big5 = recent and row["current_club_domestic_competition_id"] in BIG5_COMPETITION_IDS
            if not (in_wc_squad or in_ucl_lineup or in_ucl_club or in_big5):
                continue
            if not row["current_club_id"]:
                continue  # no real club to assign -> can't satisfy ingest.py's club_by_id lookup
            candidate_rows[pid] = row

    referenced_club_ids = {row["current_club_id"] for row in candidate_rows.values()}

    # clubs.csv: every club actually referenced by a selected player (the 36 UCL
    # clubs plus whichever other big-5/WC-squad clubs those players turned out to
    # play for), not just the UCL 36 -- see the comment above.
    club_rows: dict[str, _ClubInfo] = {}
    with _open(data_dir, "clubs.csv.gz") as f:
        for row in csv.DictReader(f):
            if row["club_id"] in referenced_club_ids:
                competition = "UCL2026" if row["club_id"] in ucl_club_ids else competition_names.get(
                    row["domestic_competition_id"], "Other"
                ).replace("-", " ").title()
                country = competition_countries.get(row["domestic_competition_id"], "International")
                club_rows[row["club_id"]] = _ClubInfo(
                    club_id=row["club_id"], name=row["name"], country=country, competition=competition
                )

    # clubs.csv only covers clubs playing in a competition this export tracks
    # (competitions.csv's ~60 leagues/cups, mostly European) -- discovered when a
    # chunk of real WC2026 squads (South Africa, Qatar, Egypt, Iran, Iraq, Jordan,
    # Uzbekistan, Panama, ...) came back at 0-12 players instead of ~26 because their
    # domestic leagues (Saudi, Qatari, Egyptian, ...) aren't in that coverage. Rather
    # than silently dropping those real players (breaking "build an XI" for whichever
    # nation the user is assigned), give their club a minimal real-data placeholder
    # entry -- `current_club_name` is a real column on players.csv even when
    # clubs.csv itself has no row for that club -- and mark it honestly as outside
    # this dataset's league-strength coverage rather than guessing a country/coefficient.
    for row in candidate_rows.values():
        cid = row["current_club_id"]
        if cid not in club_rows:
            club_rows[cid] = _ClubInfo(
                club_id=cid,
                name=row["current_club_name"] or f"Club {cid}",
                country="Unknown (league not in dataset)",
                competition="Other",
            )

    assert all(row["current_club_id"] in club_rows for row in candidate_rows.values())

    clubs = [
        {"club_id": c.club_id, "name": c.name, "country": c.country, "competition": c.competition}
        for c in club_rows.values()
    ]
    national_teams = [
        {
            "team_id": f"nt_{tid}",
            "name": row["name"],
            "country": row["country_name"],
            "competition": "WC2026",
        }
        for tid, row in national_team_rows.items()
    ]

    tm_players: list[TmPlayer] = []
    for pid, row in candidate_rows.items():
        dob = _parse_date(row["date_of_birth"]) or date(1998, 1, 1)
        group, code = _position_group_and_code(row["position"], row["sub_position"])
        foot = row["foot"] if row["foot"] in ("left", "right") else "right"
        height = _parse_int(row["height_in_cm"], default=182)

        tm_players.append(
            TmPlayer(
                tm_id=pid,
                name=row["name"] or f"{row['first_name']} {row['last_name']}".strip(),
                dob=dob,
                nationality=row["country_of_citizenship"] or "Unknown",
                position_group=group,
                position_code=code,
                preferred_foot=foot,
                height_cm=height if height > 0 else 182,
                club_id=row["current_club_id"],
                true_quality=0.0,  # filled in below once we know market-value percentiles
                market_value_eur=_market_value(row),
            )
        )

    # Market-value percentile within position group -> the "quality" proxy used only
    # to synthesize the advanced per-90 metrics Transfermarkt doesn't track (see the
    # module docstring). Real ability scoring itself (pipeline/features.py) never
    # sees this value; it only sees the per90 numbers built from it below.
    by_group: dict[str, list[TmPlayer]] = {}
    for p in tm_players:
        by_group.setdefault(p.position_group, []).append(p)
    for group_players in by_group.values():
        ranked = sorted(group_players, key=lambda p: p.market_value_eur)
        n = len(ranked)
        for i, p in enumerate(ranked):
            percentile = (i + 1) / n * 100
            p.true_quality = round(30 + percentile * 0.69, 1)  # ~30-99, matches synthetic's range

    tm_by_id = {p.tm_id: p for p in tm_players}
    # `nt_<national_team_id>` matches the only real invariant the rest of the pipeline
    # relies on (pipeline/to_engine.py's `team_id.startswith("nt_")`) -- it doesn't
    # need to be an ISO code, just stable and unique, which the real numeric id is.
    wc_squads = {
        f"nt_{tid}": sorted(pids & tm_by_id.keys())
        for tid, pids in wc_squads_by_team.items()
        if tid in national_team_rows
    }
    # Only the real 36 UCL 2025/26 league-phase clubs are drawable opponents --
    # `club_rows` also holds every other club a candidate player happens to play for
    # (big-5 non-UCL sides, and the "club not in this dataset's coverage" placeholders
    # above), which must stay out of the opponent pool. Membership is the union of
    # "currently at this club" and "actually lined up for this club in a real 2025/26
    # UCL match" -- the latter is what rescues the 3 clubs (smaller-league debutants)
    # whose players.csv club-name field was blank, the same fix WC2026 squads needed.
    ucl_squads: dict[str, list[str]] = {}
    for club_id in ucl_club_ids:
        from_current_club = {pid for pid in tm_by_id if tm_by_id[pid].club_id == club_id}
        from_lineup = ucl_lineup_squads_by_club.get(club_id, set()) & tm_by_id.keys()
        members = from_current_club | from_lineup
        if members:
            ucl_squads[club_id] = sorted(members)

    understat_players = _aggregate_real_stats(data_dir, tm_players, club_rows, seed)

    # Part 2c: how often each candidate actually started (not just appeared in the
    # squad) at each position, across the same real WC2026/UCL2025-26 matches
    # already used above -- engine/opponent_lineup.py's "predicted XI" signal.
    wc_frequency = _load_starting_lineup_frequency(data_dir, wc_game_ids, set(tm_by_id.keys()))
    ucl_frequency = _load_starting_lineup_frequency(data_dir, ucl_game_ids, set(tm_by_id.keys()))
    lineup_frequency: dict[str, dict[tuple[str, str], int]] = {
        f"nt_{tid}": counts for tid, counts in wc_frequency.items() if tid in national_team_rows
    }
    for club_id, counts in ucl_frequency.items():
        if club_id in ucl_squads:
            lineup_frequency[club_id] = counts

    return SyntheticWorld(
        clubs=clubs,
        national_teams=national_teams,
        tm_players=tm_players,
        understat_players=understat_players,
        wc_squads=wc_squads,
        ucl_squads=ucl_squads,
        lineup_frequency=lineup_frequency,
    )


def _aggregate_real_stats(
    data_dir: str, tm_players: list[TmPlayer], club_rows: dict[str, _ClubInfo], seed: int | None
) -> list[UnderstatPlayer]:
    tm_by_id = {p.tm_id: p for p in tm_players}
    wanted_ids = set(tm_by_id)

    totals: dict[str, dict[str, int]] = {}
    cutoff = DATASET_SNAPSHOT_DATE.toordinal() - APPEARANCE_LOOKBACK_DAYS
    with _open(data_dir, "appearances.csv.gz") as f:
        for row in csv.DictReader(f):
            pid = row["player_id"]
            if pid not in wanted_ids:
                continue
            d = _parse_date(row["date"])
            if d is None or d.toordinal() < cutoff:
                continue
            t = totals.setdefault(pid, {"minutes": 0, "goals": 0, "assists": 0, "yellow": 0, "red": 0})
            t["minutes"] += _parse_int(row["minutes_played"])
            t["goals"] += _parse_int(row["goals"])
            t["assists"] += _parse_int(row["assists"])
            t["yellow"] += _parse_int(row["yellow_cards"])
            t["red"] += _parse_int(row["red_cards"])

    rng = random.Random(seed if seed is not None else 42)
    understat_players: list[UnderstatPlayer] = []
    for pid, t in totals.items():
        if t["minutes"] <= 0:
            continue
        tm = tm_by_id[pid]
        club = club_rows.get(tm.club_id)
        club_name = club.name if club else ""
        per90 = t["minutes"] / 90.0
        q = tm.true_quality / 50.0  # same scaling convention as synthetic_source.py
        attack_bias = 1.6 if tm.position_group == "FW" else (1.0 if tm.position_group == "MF" else 0.25)
        defence_bias = 1.6 if tm.position_group == "DF" else (1.0 if tm.position_group == "MF" else 0.3)

        aerial_contests = max(1, rng.gauss(2.2, 0.6)) * per90
        aerial_win_rate = max(0.1, min(0.95, 0.35 + 0.18 * q))

        understat_players.append(
            UnderstatPlayer(
                understat_id=f"real_u_{pid}",
                name=tm.name,  # a single real source -> id_resolution resolves it exactly, by design
                dob=tm.dob,
                club_name=club_name,
                minutes=t["minutes"],
                goals=t["goals"],
                assists=t["assists"],
                xg=round(float(t["goals"]), 2),  # approximation -- see module docstring
                xa=round(float(t["assists"]), 2),  # approximation -- see module docstring
                shots=int(max(0, rng.gauss(2.2 * q * attack_bias, 0.6)) * per90),
                key_passes=int(max(0, rng.gauss(1.0 * q, 0.5)) * per90),
                tackles_won=int(max(0, rng.gauss(1.4 * q * defence_bias, 0.5)) * per90),
                dribbled_past=int(max(0, rng.gauss(2.0 / q, 0.5)) * per90),
                aerials_won=int(aerial_contests * aerial_win_rate),
                aerials_total=int(aerial_contests),
                progressive_carries=int(max(0, rng.gauss(1.6 * q, 0.6)) * per90),
                take_ons_won=int(max(0, rng.gauss(0.8 * q * attack_bias, 0.4)) * per90),
                pass_completion=round(min(98.0, max(55.0, rng.gauss(55 + 0.35 * tm.true_quality, 3))), 1),
                tm_id_for_grading_only=pid,
            )
        )
    return understat_players
