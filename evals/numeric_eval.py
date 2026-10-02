"""Numeric-correctness eval. docs/DESIGN.md section 12: validator pass rate on
generated reports. Unlike retrieval_eval.py, this needs no human-written golden set
-- "correct" here means "every number in the narrated text matches an engine value",
which `llm/validator.py` already checks mechanically against the engine's own output.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Club, NationalTeam
from engine.optimizer import find_optimal_lineup
from engine.optimizer import manager_score as compute_manager_score
from engine.rating import get_default_rating_model
from engine.rules import validate_lineup
from engine.schemas import LineupAnalysis
from engine.simulation import simulate_match
from engine.swaps import swaps_by_weakness
from engine.weaknesses import find_weaknesses
from llm.narrator import narrate_coach_report, narrate_match_report
from llm.provider import Provider, get_provider
from pipeline.to_engine import load_candidate_pool, load_squad_player_ids, load_team_name, load_team_profile


@dataclass
class NumericEvalReport:
    n_samples: int
    coach_report_pass_rate: float
    match_report_pass_rate: float
    fallback_count: int


async def run_numeric_eval(
    session: AsyncSession, *, n_samples: int = 10, seed: int = 42, provider: Provider | None = None
) -> NumericEvalReport:
    provider = provider or get_provider()
    rating_model = get_default_rating_model()
    rng = random.Random(seed)

    national_ids = (await session.execute(select(NationalTeam.team_id))).scalars().all()
    club_ids = (await session.execute(select(Club.club_id))).scalars().all()
    all_team_ids = [*national_ids, *club_ids]
    if not all_team_ids:
        return NumericEvalReport(n_samples=0, coach_report_pass_rate=0.0, match_report_pass_rate=0.0, fallback_count=0)

    sample_teams = rng.sample(all_team_ids, min(n_samples, len(all_team_ids)))

    coach_passes = 0
    match_passes = 0
    fallback_count = 0

    for team_id in sample_teams:
        opponent_ids = await load_squad_player_ids(session, team_id)
        pool = await load_candidate_pool(session, exclude_ids=opponent_ids, limit=400)
        lineup = find_optimal_lineup("4-3-3", pool, opponent_ids, time_limit_seconds=5.0)
        if lineup is None:
            continue

        opponent_name = await load_team_name(session, team_id)
        opponent_profile = await load_team_profile(session, team_id, opponent_name, "4-2-3-1")

        rating = rating_model.rate(lineup, opponent_profile)
        weaknesses = find_weaknesses(lineup, opponent_profile)
        swaps = swaps_by_weakness(lineup, opponent_profile, weaknesses, pool, opponent_ids, rating_model)
        mgr = compute_manager_score(lineup, opponent_profile, pool, opponent_ids, rating_model)
        validation = validate_lineup(lineup, opponent_ids)
        sim = simulate_match(rating, lineup, opponent_profile, runs=500, seed=seed)

        analysis = LineupAnalysis(
            session_id="eval", formation=lineup.formation, rating=rating, weaknesses=weaknesses,
            swaps_by_weakness=swaps, manager_score=mgr, validation=validation,
            win_draw_loss=(sim.win_pct, sim.draw_pct, sim.loss_pct),
        )

        coach_result = narrate_coach_report(analysis, opponent_name, provider)
        match_result = narrate_match_report(sim, opponent_name, provider)

        coach_passes += int(coach_result.passed)
        match_passes += int(match_result.passed)
        fallback_count += int(coach_result.used_fallback) + int(match_result.used_fallback)

    n = len(sample_teams)
    return NumericEvalReport(
        n_samples=n,
        coach_report_pass_rate=round(coach_passes / n, 3) if n else 0.0,
        match_report_pass_rate=round(match_passes / n, 3) if n else 0.0,
        fallback_count=fallback_count,
    )
