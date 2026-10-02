"""End-to-end LangGraph integration test. Implements the Phase 5 acceptance check:
"a full session can be run from a Python script end to end."
"""

from __future__ import annotations

import os

import pytest
from langgraph.types import Command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# DATA_SOURCE now defaults to "real" (docs/DECISIONS.md "Synthetic data is no longer
# the silent default") -- tests opt into synthetic explicitly so they don't need
# data_raw/ in CI.
os.environ["DATA_SOURCE"] = "synthetic"

from config.game import COUNTER_MAX_ROUNDS  # noqa: E402
from engine.optimizer import find_optimal_lineup
from graph.graph import build_graph
from pipeline.features import compute_features
from pipeline.ingest import run_ingest
from pipeline.pricing import compute_prices
from pipeline.team_profiles import compute_team_profiles
from pipeline.to_engine import load_candidate_pool, load_squad_player_ids

SEED = 42


@pytest.fixture
async def ready_engine(tmp_path):
    db_path = tmp_path / "graph_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await run_ingest(engine, seed=SEED, output_dir=str(tmp_path))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await compute_features(session)
    async with session_factory() as session:
        await compute_prices(session, seed=SEED)
    async with session_factory() as session:
        await compute_team_profiles(session)
    yield engine
    await engine.dispose()


async def _optimal_assignments(engine, opponent_team_id: str) -> dict[str, str]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        opp_ids = await load_squad_player_ids(session, opponent_team_id)
        pool = await load_candidate_pool(session, exclude_ids=opp_ids, limit=400)
    best = find_optimal_lineup("4-3-3", pool, opp_ids, time_limit_seconds=8.0)
    assert best is not None
    return {slot: c.player_id for slot, c in best.assignments.items()}


async def test_full_session_build_lock_in_chat_end(ready_engine) -> None:
    graph = build_graph(ready_engine, seed=SEED)
    config = {"configurable": {"thread_id": "it-1"}}

    state = await graph.ainvoke({"mode": "wc", "session_id": "it-1"}, config)
    assert state["opponent_team_id"].startswith("nt_")
    assert state.get("__interrupt__")  # paused at build

    assignments = await _optimal_assignments(ready_engine, state["opponent_team_id"])
    state = await graph.ainvoke(Command(resume={"formation": "4-3-3", "assignments": assignments}), config)

    assert state.get("analysis") is not None
    assert 0.0 <= state["analysis"]["rating"]["overall"] <= 100.0
    assert state["analysis"]["validation"]["valid"]
    assert state.get("coach_report_text")
    interrupt = state["__interrupt__"][0].value
    assert interrupt["awaiting"] == "decision"

    state = await graph.ainvoke(Command(resume={"decision": "lock_in"}), config)
    assert state.get("simulation") is not None
    assert state.get("match_report_text")
    interrupt = state["__interrupt__"][0].value
    assert interrupt["awaiting"] == "question"

    state = await graph.ainvoke(Command(resume={"question": "what are the odds?"}), config)
    assert len(state["messages"]) == 2
    assert "%" in state["messages"][-1]["content"]

    state = await graph.ainvoke(Command(resume={"end": True}), config)
    assert state.get("__interrupt__") is None
    assert graph.get_state(config).next == ()


async def test_counter_round_cap_through_graph(ready_engine) -> None:
    graph = build_graph(ready_engine, seed=SEED)
    config = {"configurable": {"thread_id": "it-2"}}

    state = await graph.ainvoke({"mode": "wc", "session_id": "it-2"}, config)
    assignments = await _optimal_assignments(ready_engine, state["opponent_team_id"])
    state = await graph.ainvoke(Command(resume={"formation": "4-3-3", "assignments": assignments}), config)

    for expected_round in range(1, COUNTER_MAX_ROUNDS + 2):
        state = await graph.ainvoke(Command(resume={"decision": "counter"}), config)
        assert state["counter_round"] == min(expected_round, COUNTER_MAX_ROUNDS)

    # one more round than the cap should have landed us at simulate/chat, not stuck looping
    assert state.get("simulation") is not None
    assert len(state["counter_history"]) == COUNTER_MAX_ROUNDS


async def test_invalid_lineup_loops_back_to_build(ready_engine) -> None:
    graph = build_graph(ready_engine, seed=SEED)
    config = {"configurable": {"thread_id": "it-3"}}

    state = await graph.ainvoke({"mode": "wc", "session_id": "it-3"}, config)
    opponent_team_id = state["opponent_team_id"]

    session_factory = async_sessionmaker(ready_engine, expire_on_commit=False)
    async with session_factory() as session:
        opp_ids = await load_squad_player_ids(session, opponent_team_id)
        pool = await load_candidate_pool(session, exclude_ids=opp_ids, limit=400)
    by_group: dict[str, list] = {}
    for c in pool:
        by_group.setdefault(c.position_group, []).append(c)
    slots = {
        "GK": "GK", "LB": "DF", "CB1": "DF", "CB2": "DF", "RB": "DF", "DM": "MF",
        "LCM": "MF", "RCM": "MF", "LW": "FW", "ST": "FW", "RW": "FW",
    }
    # deliberately pick the most expensive player per slot -- almost certainly over budget
    too_expensive = {
        slot: max(by_group[grp], key=lambda c: c.price_eur).player_id for slot, grp in slots.items()
    }

    state = await graph.ainvoke(Command(resume={"formation": "4-3-3", "assignments": too_expensive}), config)
    interrupt = state["__interrupt__"][0].value
    assert interrupt["awaiting"] == "lineup"  # bounced back to build, never reached analyse
    assert state.get("analysis") is None
