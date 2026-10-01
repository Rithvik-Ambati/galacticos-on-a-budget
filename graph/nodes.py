"""Node functions. docs/DESIGN.md section 10:
draw -> scout -> build (interrupt) -> validate -> analyse -> narrate_report ->
user_decision (interrupt) -> opponent_counter -> [loop] -> simulate -> narrate_match -> chat.

Each node re-hydrates engine objects from the DB by id (graph/state.py's docstring) --
engine/ itself never touches the DB directly.
"""

from __future__ import annotations

import random
from typing import Any

from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine as SAAsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.game import COUNTER_MAX_ROUNDS
from db.models import Club, NationalTeam
from engine.analyse import build_analysis
from engine.counter import run_counter_round
from engine.rating import get_default_rating_model
from engine.rules import validate_lineup
from engine.schemas import Lineup, PlayerCard
from engine.simulation import simulate_match, simulate_two_legs
from graph.state import GameState
from llm.narrator import narrate_coach_report, narrate_match_report
from llm.provider import get_provider
from pipeline.to_engine import (
    load_candidate_pool,
    load_player_card,
    load_squad_player_cards,
    load_squad_player_ids,
    load_team_profile,
)

TOURNAMENT_BY_MODE = {"wc": "WC2026", "ucl": "UCL2026"}


async def _lineup_from_state(session: AsyncSession, state: GameState) -> Lineup:
    assignments: dict[str, PlayerCard] = {}
    for slot_id, player_id in state.get("lineup_assignments", {}).items():
        card = await load_player_card(session, player_id)
        if card is not None:
            assignments[slot_id] = card
    return Lineup(formation=state["formation"], assignments=assignments)


OPPONENT_INITIAL_FORMATION = "4-2-3-1"


async def _opponent_lineup_from_state(session: AsyncSession, state: GameState) -> Lineup:
    assignments: dict[str, PlayerCard] = {}
    for slot_id, player_id in state.get("opponent_lineup_assignments", {}).items():
        card = await load_player_card(session, player_id)
        if card is not None:
            assignments[slot_id] = card
    formation = state.get("opponent_formation") or OPPONENT_INITIAL_FORMATION
    return Lineup(formation=formation, assignments=assignments)


def make_nodes(engine: SAAsyncEngine, seed: int = 42) -> dict[str, Any]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    rating_model = get_default_rating_model()
    provider = get_provider()

    async def draw(state: GameState) -> dict[str, Any]:
        tournament = TOURNAMENT_BY_MODE[state["mode"]]
        async with session_factory() as session:
            if tournament == "WC2026":
                teams = (await session.execute(select(NationalTeam.team_id))).scalars().all()
            else:
                teams = (await session.execute(select(Club.club_id))).scalars().all()
        rng = random.Random(f"{state['session_id']}:{seed}")
        opponent_team_id = rng.choice(sorted(teams))

        async with session_factory() as session:
            squad = await load_squad_player_cards(session, opponent_team_id)
        by_group: dict[str, list[PlayerCard]] = {}
        for c in squad:
            by_group.setdefault(c.position_group, []).append(c)
        opponent_formation_slots = {
            "GK": ("GK", 1), "RB": ("DF", 1), "CB1": ("DF", 1), "CB2": ("DF", 1), "LB": ("DF", 1),
            "DM1": ("MF", 1), "DM2": ("MF", 1), "LAM": ("MF", 1), "CAM": ("MF", 1), "RAM": ("MF", 1),
            "ST": ("FW", 1),
        }
        assignments: dict[str, str] = {}
        used: set[str] = set()
        for slot_id, (group, _n) in opponent_formation_slots.items():
            pool = sorted((c for c in by_group.get(group, []) if c.player_id not in used), key=lambda c: -c.ability_score)
            if pool:
                assignments[slot_id] = pool[0].player_id
                used.add(pool[0].player_id)

        return {
            "opponent_team_id": opponent_team_id,
            "opponent_formation": OPPONENT_INITIAL_FORMATION,
            "opponent_lineup_assignments": assignments,
            "counter_round": 0,
            "counter_history": [],
        }

    async def scout(state: GameState) -> dict[str, Any]:
        return {}  # the scouting report is read straight off opponent_team_id by the API layer

    async def build(state: GameState) -> dict[str, Any]:
        payload = interrupt({"awaiting": "lineup", "formation": state.get("formation", "4-3-3")})
        return {
            "formation": payload.get("formation", state.get("formation", "4-3-3")),
            "lineup_assignments": payload["assignments"],
        }

    async def validate(state: GameState) -> dict[str, Any]:
        async with session_factory() as session:
            lineup = await _lineup_from_state(session, state)
            opponent_ids = await load_squad_player_ids(session, state["opponent_team_id"])
        result = validate_lineup(lineup, opponent_ids)
        return {"validation_ok": result.valid and result.filled_slots == 11}

    def validate_router(state: GameState) -> str:
        return "analyse" if state.get("validation_ok") else "build"

    async def analyse(state: GameState) -> dict[str, Any]:
        async with session_factory() as session:
            lineup = await _lineup_from_state(session, state)
            opponent_squad_ids = await load_squad_player_ids(session, state["opponent_team_id"])
            opponent_lineup = await _opponent_lineup_from_state(session, state)
            opponent_profile = await load_team_profile(
                session, state["opponent_team_id"], state["opponent_team_id"], opponent_lineup.formation
            )
            candidate_pool = await load_candidate_pool(session, exclude_ids=opponent_squad_ids)

            analysis = build_analysis(
                lineup, opponent_profile, opponent_squad_ids, candidate_pool,
                opponent_lineup=opponent_lineup, session_id=state["session_id"],
            )
        return {"analysis": analysis.model_dump()}

    async def narrate_report(state: GameState) -> dict[str, Any]:
        from engine.schemas import LineupAnalysis

        analysis = LineupAnalysis.model_validate(state["analysis"])
        text = narrate_coach_report(analysis, state["opponent_team_id"], provider)
        return {"coach_report_text": text.text}

    async def user_decision(state: GameState) -> dict[str, Any]:
        payload = interrupt({"awaiting": "decision", "round": state.get("counter_round", 0)})
        return {"decision": payload["decision"]}

    def decision_router(state: GameState) -> str:
        if state.get("decision") == "counter" and state.get("counter_round", 0) < COUNTER_MAX_ROUNDS:
            return "opponent_counter"
        return "simulate"

    async def opponent_counter(state: GameState) -> dict[str, Any]:
        async with session_factory() as session:
            lineup = await _lineup_from_state(session, state)
            opponent_lineup = await _opponent_lineup_from_state(session, state)
            opponent_profile = await load_team_profile(
                session, state["opponent_team_id"], state["opponent_team_id"], opponent_lineup.formation
            )
            squad = await load_squad_player_cards(session, state["opponent_team_id"])

            round_number = state.get("counter_round", 0) + 1
            result, new_opponent_lineup = run_counter_round(
                round_number, lineup, opponent_lineup, opponent_profile, squad, rating_model
            )
        return {
            "counter_round": round_number,
            "counter_history": [*state.get("counter_history", []), result.model_dump()],
            "opponent_formation": new_opponent_lineup.formation,
            "opponent_lineup_assignments": {
                slot_id: p.player_id for slot_id, p in new_opponent_lineup.assignments.items()
            },
            "decision": None,
        }

    async def simulate(state: GameState) -> dict[str, Any]:
        async with session_factory() as session:
            lineup = await _lineup_from_state(session, state)
            opponent_lineup = await _opponent_lineup_from_state(session, state)
            opponent_profile = await load_team_profile(
                session, state["opponent_team_id"], state["opponent_team_id"], opponent_lineup.formation
            )
            if state["mode"] == "ucl":
                sim = simulate_two_legs(rating_model, lineup, opponent_profile, opponent_lineup=opponent_lineup)
            else:
                rating = rating_model.rate(lineup, opponent_profile, opponent_lineup)
                sim = simulate_match(rating, lineup, opponent_profile, opponent_lineup=opponent_lineup)
        return {"simulation": sim.model_dump()}

    async def narrate_match(state: GameState) -> dict[str, Any]:
        from engine.schemas import SimulationResult

        sim = SimulationResult.model_validate(state["simulation"])
        text = narrate_match_report(sim, state["opponent_team_id"], provider)
        return {"match_report_text": text.text}

    async def chat(state: GameState) -> dict[str, Any]:
        from graph.chat_tools import answer_question

        payload = interrupt({"awaiting": "question"})
        if payload.get("end"):
            return {"_chat_ended": True}

        question = payload["question"]
        async with session_factory() as session:
            answer = await answer_question(session, question, state, provider)
        messages = [
            *state.get("messages", []),
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
        return {"messages": messages, "_chat_ended": False}

    def chat_router(state: GameState) -> str:
        return "__end__" if state.get("_chat_ended") else "chat"

    return {
        "draw": draw,
        "scout": scout,
        "build": build,
        "validate": validate,
        "validate_router": validate_router,
        "analyse": analyse,
        "narrate_report": narrate_report,
        "user_decision": user_decision,
        "decision_router": decision_router,
        "opponent_counter": opponent_counter,
        "simulate": simulate,
        "narrate_match": narrate_match,
        "chat": chat,
        "chat_router": chat_router,
    }
