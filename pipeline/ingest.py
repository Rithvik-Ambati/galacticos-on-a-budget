"""Loads the (synthetic, see docs/DECISIONS.md) Transfermarkt+Understat sources, runs
id_resolution, and writes players/clubs/national_teams/squads/player_stats_season.

Implements the Phase 1 prompt's ingest + id_resolution + squad-loading steps.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from db.bootstrap import create_all
from db.models import Club, IngestMetadata, NationalTeam, Player, PlayerIdMap, PlayerStatsSeason, Squad
from pipeline import data_source, id_resolution, real_source

TOP_LEAGUE_COEFFICIENT = 1.0
OTHER_LEAGUE_COEFFICIENT = 0.82
FALLBACK_LEAGUE_STRENGTH = 0.5  # below this, pipeline/features.py flags low confidence
# Synthetic data uses ISO3 codes; pipeline/real_source.py uses full country names
# (from the real dataset's competitions.csv) -- both are valid "club['country']"
# values depending on DATA_SOURCE, so this set covers both.
TOP_LEAGUE_COUNTRIES = {"ESP", "ENG", "GER", "ITA", "FRA", "Spain", "England", "Germany", "Italy", "France"}


@dataclass
class IngestSummary:
    player_count: int
    club_count: int
    national_team_count: int
    squad_rows: int
    stats_rows: int
    matched_count: int
    unresolved_count: int
    unresolved_csv_path: str


async def run_ingest(engine: AsyncEngine, *, seed: int | None = None, output_dir: str = "data") -> IngestSummary:
    os.makedirs(output_dir, exist_ok=True)
    await create_all(engine)

    source_name = data_source.resolve_source_name()
    world = data_source.generate(seed=seed)
    matches, unresolved = id_resolution.resolve(world.tm_players, world.understat_players, world.clubs)

    csv_path = os.path.join(output_dir, "unresolved_ids.csv")
    id_resolution.write_unresolved_csv(unresolved, csv_path)

    understat_by_id = {u.understat_id: u for u in world.understat_players}
    club_by_id = {c["club_id"]: c for c in world.clubs}
    tm_by_id = {p.tm_id: p for p in world.tm_players}

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add_all(
            Club(club_id=c["club_id"], name=c["name"], country=c["country"], competition=c["competition"])
            for c in world.clubs
        )
        session.add_all(
            NationalTeam(team_id=t["team_id"], name=t["name"], country=t["country"], competition=t["competition"])
            for t in world.national_teams
        )
        session.add_all(
            Player(
                player_id=p.tm_id,
                name=p.name,
                dob=p.dob,
                nationality=p.nationality,
                positions=[p.position_code],
                preferred_foot=p.preferred_foot,
                height_cm=p.height_cm,
                current_club_id=p.club_id,
            )
            for p in world.tm_players
        )
        await session.flush()

        session.add_all(
            PlayerIdMap(
                player_id=m.player_id,
                tm_id=m.tm_id,
                understat_id=m.understat_id,
                statsbomb_id=m.statsbomb_id,
                match_method=m.match_method,
                match_score=m.match_score,
            )
            for m in matches
        )

        squad_rows = 0
        for team_id, player_ids in world.wc_squads.items():
            session.add_all(
                Squad(team_id=team_id, team_type="national", tournament="WC2026", player_id=pid)
                for pid in player_ids
            )
            squad_rows += len(player_ids)
        for club_id, player_ids in world.ucl_squads.items():
            session.add_all(
                Squad(team_id=club_id, team_type="club", tournament="UCL2026", player_id=pid)
                for pid in player_ids
            )
            squad_rows += len(player_ids)

        stats_rows = []
        for m in matches:
            u = understat_by_id[m.understat_id]
            tm = tm_by_id[m.tm_id]
            club = club_by_id[tm.club_id]
            coeff = TOP_LEAGUE_COEFFICIENT if club["country"] in TOP_LEAGUE_COUNTRIES else OTHER_LEAGUE_COEFFICIENT
            stats_rows.append(
                PlayerStatsSeason(
                    player_id=m.player_id,
                    season="2025-26",
                    competition=club["competition"],
                    minutes=u.minutes,
                    goals=u.goals,
                    assists=u.assists,
                    xg=u.xg,
                    xa=u.xa,
                    shots=u.shots,
                    key_passes=u.key_passes,
                    tackles_won=u.tackles_won,
                    dribbled_past=u.dribbled_past,
                    aerials_won=u.aerials_won,
                    aerials_total=u.aerials_total,
                    progressive_carries=u.progressive_carries,
                    take_ons_won=u.take_ons_won,
                    pass_completion=u.pass_completion,
                    league_strength=coeff,
                )
            )
        # Players outside Understat's coverage still get a basic appearance-stats row
        # (minutes/goals/assists only) per docs/DESIGN.md section 5's documented
        # fallback -- never a full-stats row faked up to look like real coverage.
        fallback_rng = random.Random((seed if seed is not None else 0) + 1)
        matched_tm_ids = {m.tm_id for m in matches}
        for tm in world.tm_players:
            if tm.tm_id in matched_tm_ids:
                continue
            club = club_by_id[tm.club_id]
            minutes = fallback_rng.randint(200, 2600)
            per90 = minutes / 90.0
            stats_rows.append(
                PlayerStatsSeason(
                    player_id=tm.tm_id,
                    season="2025-26",
                    competition=club["competition"],
                    minutes=minutes,
                    goals=int(max(0, fallback_rng.gauss(tm.true_quality / 100, 0.4)) * per90 * 0.3),
                    assists=int(max(0, fallback_rng.gauss(tm.true_quality / 100, 0.3)) * per90 * 0.2),
                    xg=0.0,
                    xa=0.0,
                    shots=0,
                    key_passes=0,
                    tackles_won=0,
                    dribbled_past=0,
                    aerials_won=0,
                    aerials_total=0,
                    progressive_carries=0,
                    take_ons_won=0,
                    pass_completion=0.0,
                    league_strength=FALLBACK_LEAGUE_STRENGTH,
                )
            )
        session.add_all(stats_rows)

        # Written on every run, real or synthetic (docs/DECISIONS.md "Synthetic data
        # is no longer the silent default") -- api/main.py's startup refuses to boot
        # without at least one row here, and the frontend shows a persistent demo
        # banner whenever the most recent row says "synthetic".
        session.add(
            IngestMetadata(
                data_source=source_name,
                dataset_snapshot_date=(
                    real_source.DATASET_SNAPSHOT_DATE.isoformat() if source_name == "real" else None
                ),
            )
        )

        await session.commit()

    return IngestSummary(
        player_count=len(world.tm_players),
        club_count=len(world.clubs),
        national_team_count=len(world.national_teams),
        squad_rows=squad_rows,
        stats_rows=len(stats_rows),
        matched_count=len(matches),
        unresolved_count=len(unresolved),
        unresolved_csv_path=csv_path,
    )
