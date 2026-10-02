"""Shared sample generation for evals/numeric_eval.py and evals/faithfulness_eval.py --
both need the same "pick a real opponent, build the best legal lineup against it, run
it through the whole engine + narrator pipeline" setup; this is the one place that
logic lives so the two evals can't silently drift apart on how a sample is built.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Squad
from engine.optimizer import find_optimal_lineup
from engine.optimizer import manager_score as compute_manager_score
from engine.rating import get_default_rating_model
from engine.rules import validate_lineup
from engine.schemas import LineupAnalysis, SimulationResult
from engine.simulation import simulate_match
from engine.swaps import swaps_by_weakness
from engine.weaknesses import find_weaknesses
from llm.narrator import (
    _coach_report_allowed_values,
    _coach_report_template,
    _match_report_allowed_values,
    _match_report_template,
    narrate_coach_report,
    narrate_match_report,
)
from llm.provider import Provider, get_provider
from llm.validator import ValidatedText
from pipeline.to_engine import load_candidate_pool, load_squad_player_ids, load_team_name, load_team_profile


@dataclass
class ReportSample:
    opponent_name: str
    analysis: LineupAnalysis
    sim: SimulationResult
    coach_template: str  # the engine-grounded facts given to the LLM to restyle
    coach_result: ValidatedText
    coach_allowed_values: set[float]
    match_template: str
    match_result: ValidatedText
    match_allowed_values: set[float]


async def generate_report_samples(
    session: AsyncSession, *, n_samples: int = 10, seed: int = 42, provider: Provider | None = None
) -> list[ReportSample]:
    provider = provider or get_provider()
    rating_model = get_default_rating_model()
    rng = random.Random(seed)

    # Squad.team_id, not Club/NationalTeam directly -- those tables also hold every
    # other real club/team a candidate player happens to be linked to, most of which
    # have no Squad row at all (same bug graph/nodes.py::draw() had, docs/DECISIONS.md
    # "Thin squads"). Deduplicated across tournaments since these evals don't care
    # which mode a team belongs to.
    all_team_ids = list((await session.execute(select(Squad.team_id).distinct())).scalars().all())
    if not all_team_ids:
        return []

    sample_teams = rng.sample(all_team_ids, min(n_samples, len(all_team_ids)))
    samples: list[ReportSample] = []

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

        samples.append(
            ReportSample(
                opponent_name=opponent_name,
                analysis=analysis,
                sim=sim,
                coach_template=_coach_report_template(analysis, opponent_name),
                coach_result=narrate_coach_report(analysis, opponent_name, provider),
                coach_allowed_values=_coach_report_allowed_values(analysis),
                match_template=_match_report_template(sim, opponent_name),
                match_result=narrate_match_report(sim, opponent_name, provider),
                match_allowed_values=_match_report_allowed_values(sim),
            )
        )

    return samples
