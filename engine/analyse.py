"""CLI: python -m engine.analyse --opponent <team> --lineup lineup.json

Implements the Phase 3 prompt's CLI requirement, extended by Phase 4 with --counter
and --simulate. Prints the full analysis as JSON (CLAUDE.md: Pydantic models for
anything crossing a module boundary, so this is literally LineupAnalysis.model_dump_json()).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import TypeVar

from pydantic import BaseModel

from engine import counter as counter_mod
from engine import simulation as simulation_mod
from engine.demo_fixtures import (
    BRAZIL_OPPONENT_LINEUP,
    BRAZIL_PROFILE,
    BRAZIL_SQUAD,
    BRAZIL_SQUAD_IDS,
    CANDIDATE_POOL,
    build_demo_lineup,
)
from engine.optimizer import manager_score
from engine.rating import get_default_rating_model
from engine.rules import validate_lineup
from engine.schemas import Lineup, LineupAnalysis, PlayerCard, TeamProfile
from engine.swaps import swaps_by_weakness
from engine.weaknesses import find_weaknesses

ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_json_model(path: str, model: type[ModelT]) -> ModelT:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return model.model_validate(data)


def build_analysis(
    lineup: Lineup,
    opponent: TeamProfile,
    opponent_squad_player_ids: set[str],
    candidate_pool: list[PlayerCard],
    opponent_lineup: Lineup | None = None,
    session_id: str | None = None,
) -> LineupAnalysis:
    rating_model = get_default_rating_model()
    validation = validate_lineup(lineup, opponent_squad_player_ids)
    rating = rating_model.rate(lineup, opponent, opponent_lineup)
    weaknesses = find_weaknesses(lineup, opponent)
    swaps = swaps_by_weakness(
        lineup, opponent, weaknesses, candidate_pool, opponent_squad_player_ids, rating_model
    )
    mgr = manager_score(lineup, opponent, candidate_pool, opponent_squad_player_ids, rating_model)
    sim = simulation_mod.simulate_match(
        rating, lineup, opponent, opponent_lineup=opponent_lineup, runs=2000
    )

    return LineupAnalysis(
        session_id=session_id or uuid.uuid4().hex,
        formation=lineup.formation,
        rating=rating,
        weaknesses=weaknesses,
        swaps_by_weakness=swaps,
        manager_score=mgr,
        validation=validation,
        win_draw_loss=(sim.win_pct, sim.draw_pct, sim.loss_pct),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyse a lineup against an opponent.")
    parser.add_argument("--demo", action="store_true", help="use the built-in Brazil demo fixtures")
    parser.add_argument("--scenario", default="strong", choices=["strong", "weak_leftback", "all_attack"])
    parser.add_argument("--opponent", help="path to a TeamProfile JSON file")
    parser.add_argument("--lineup", help="path to a Lineup JSON file")
    parser.add_argument("--opponent-squad", help="path to a JSON list of opponent PlayerCard")
    parser.add_argument("--candidate-pool", help="path to a JSON list of eligible PlayerCard")
    parser.add_argument("--counter", action="store_true", help="also run up to 3 opponent counter rounds")
    parser.add_argument("--simulate", action="store_true", help="also run a full 10,000-run simulation")
    parser.add_argument("--mode", default="wc", choices=["wc", "ucl"])
    args = parser.parse_args(argv)

    if args.demo:
        lineup = build_demo_lineup(args.scenario)
        opponent = BRAZIL_PROFILE
        opponent_squad_ids = BRAZIL_SQUAD_IDS
        candidate_pool = CANDIDATE_POOL
        opponent_lineup = BRAZIL_OPPONENT_LINEUP
    else:
        if not (args.opponent and args.lineup and args.opponent_squad):
            parser.error("either --demo, or all of --opponent/--lineup/--opponent-squad")
        lineup = _load_json_model(args.lineup, Lineup)
        opponent = _load_json_model(args.opponent, TeamProfile)
        with open(args.opponent_squad, encoding="utf-8") as f:
            squad_data = json.load(f)
        opponent_squad = [PlayerCard.model_validate(p) for p in squad_data]
        opponent_squad_ids = {p.player_id for p in opponent_squad}
        candidate_pool = []
        if args.candidate_pool:
            with open(args.candidate_pool, encoding="utf-8") as f:
                candidate_pool = [PlayerCard.model_validate(p) for p in json.load(f)]
        opponent_lineup = None

    analysis = build_analysis(lineup, opponent, opponent_squad_ids, candidate_pool, opponent_lineup)
    output: dict[str, object] = {"analysis": analysis.model_dump()}

    if args.counter and opponent_lineup is not None:
        rating_model = get_default_rating_model()
        rounds = []
        current_opponent_lineup = opponent_lineup
        squad_pool = BRAZIL_SQUAD if args.demo else []
        for round_number in range(1, 4):
            result, current_opponent_lineup = counter_mod.run_counter_round(
                round_number, lineup, current_opponent_lineup, opponent, squad_pool, rating_model
            )
            rounds.append(result.model_dump())
        output["counter_rounds"] = rounds

    if args.simulate:
        rating_model = get_default_rating_model()
        rating = rating_model.rate(lineup, opponent, opponent_lineup)
        if args.mode == "ucl":
            sim = simulation_mod.simulate_two_legs(rating_model, lineup, opponent, opponent_lineup=opponent_lineup)
        else:
            sim = simulation_mod.simulate_match(rating, lineup, opponent, opponent_lineup=opponent_lineup)
        output["simulation"] = sim.model_dump()

    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
