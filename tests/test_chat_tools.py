"""Integration tests for graph/chat_tools.py's answer_question, driven through a
real LangGraph session exactly like the user's reported bad transcript:

    - "Which of my players has the most assists" -> returned a raw, out-of-squad
      player_profile document.
    - follow-up "from my squad not in overall" -> returned the OPPONENT's raw team
      profile, including the internal id "nt_3589".
    - "Why did we win?" (after a simulated win) -> "I don't have enough data".
    - "Who are the best rated players?" -> the global list, not the user's squad.
    - "What are the odds?" -> correct.

Each test below locks in the fix for one of those bugs: correct scope (my XI vs
opponent vs global), no internal ids, no raw document text, and the right
tool/branch being hit.
"""

from __future__ import annotations

import os

import pytest
from langgraph.types import Command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ["DATA_SOURCE"] = "synthetic"

from engine.optimizer import find_optimal_lineup  # noqa: E402
from graph.graph import build_graph  # noqa: E402
from pipeline.features import compute_features  # noqa: E402
from pipeline.ingest import run_ingest  # noqa: E402
from pipeline.pricing import compute_prices  # noqa: E402
from pipeline.team_profiles import compute_team_profiles  # noqa: E402
from pipeline.to_engine import load_candidate_pool, load_squad_player_ids  # noqa: E402

SEED = 42
_INTERNAL_ID_MARKERS = ("nt_", "club_")


@pytest.fixture
async def ready_engine(tmp_path):
    db_path = tmp_path / "chat_test.db"
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


@pytest.fixture
async def locked_in_session(ready_engine):
    """A full session through simulate -- lineup locked in, match simulated,
    post-match analysis available -- parked at the chat interrupt, exactly where
    the user's real transcript was when they asked these questions."""
    graph = build_graph(ready_engine, seed=SEED)
    config = {"configurable": {"thread_id": "chat-it"}}

    state = await graph.ainvoke({"mode": "wc", "session_id": "chat-it"}, config)
    opponent_team_id = state["opponent_team_id"]
    assignments = await _optimal_assignments(ready_engine, opponent_team_id)
    state = await graph.ainvoke(Command(resume={"formation": "4-3-3", "assignments": assignments}), config)
    assert state.get("analysis") is not None

    state = await graph.ainvoke(Command(resume={"decision": "lock_in"}), config)
    assert state.get("simulation") is not None
    assert state.get("post_match_analysis") is not None

    return graph, config, set(assignments.values()), opponent_team_id


def _no_leaked_internal_ids(text: str) -> bool:
    return not any(marker in text for marker in _INTERNAL_ID_MARKERS)


async def test_my_players_assists_question_is_scoped_to_my_xi(locked_in_session) -> None:
    graph, config, _my_ids, _opponent_team_id = locked_in_session

    state = await graph.ainvoke(Command(resume={"question": "Which of my players has the most assists"}), config)
    answer = state["messages"][-1]["content"]

    assert _no_leaked_internal_ids(answer)
    assert "Most assists in your XI" in answer
    # the old bug returned a raw player_profile document verbatim (e.g. "Ability
    # score: 39.9/100. Best-fit role: ...") for whichever player scored highest
    # globally -- that template sentence must never appear in a stats answer.
    assert "Ability score:" not in answer


async def test_followup_scoped_to_my_squad_not_opponent(locked_in_session) -> None:
    """Regression for the exact second bug: the follow-up carries no topic word
    of its own ("from my squad not in overall") and must be resolved as a
    continuation of the previous "assists" question, scoped to the user's XI --
    never to the opponent's raw team profile."""
    graph, config, _my_ids, opponent_team_id = locked_in_session

    await graph.ainvoke(Command(resume={"question": "Which of my players has the most assists"}), config)
    state = await graph.ainvoke(Command(resume={"question": "from my squad not in overall"}), config)
    answer = state["messages"][-1]["content"]

    assert _no_leaked_internal_ids(answer)
    assert opponent_team_id not in answer
    assert "Most assists in your XI" in answer
    assert "Team " not in answer  # the opponent_report template's leading clause


async def test_why_did_we_win_uses_simulation_and_postmatch(locked_in_session) -> None:
    graph, config, _my_ids, _opponent_team_id = locked_in_session

    state = await graph.ainvoke(Command(resume={"question": "Why did we win?"}), config)
    answer = state["messages"][-1]["content"]

    assert answer != "I don't have enough data to answer that confidently yet."
    assert _no_leaked_internal_ids(answer)
    assert any(word in answer for word in ("won", "lost", "drew"))
    assert "-" in answer  # the scoreline


async def test_best_rated_players_defaults_to_my_squad(locked_in_session) -> None:
    graph, config, _my_ids, _opponent_team_id = locked_in_session

    state = await graph.ainvoke(Command(resume={"question": "Who are the best rated players?"}), config)
    answer = state["messages"][-1]["content"]

    assert _no_leaked_internal_ids(answer)
    assert "your XI" in answer
    assert "the full player pool" not in answer


async def test_best_rated_players_overall_is_explicitly_global(locked_in_session) -> None:
    graph, config, _my_ids, _opponent_team_id = locked_in_session

    state = await graph.ainvoke(Command(resume={"question": "Who are the best rated players overall?"}), config)
    answer = state["messages"][-1]["content"]

    assert "the full player pool" in answer


async def test_what_are_the_odds_still_reads_the_simulation(locked_in_session) -> None:
    graph, config, _my_ids, _opponent_team_id = locked_in_session

    state = await graph.ainvoke(Command(resume={"question": "What are the odds?"}), config)
    answer = state["messages"][-1]["content"]

    assert "%" in answer
    assert "win" in answer and "draw" in answer and "loss" in answer


async def test_opponent_scoped_question_uses_opponent_squad_not_mine(locked_in_session) -> None:
    graph, config, _my_ids, _opponent_team_id = locked_in_session

    state = await graph.ainvoke(Command(resume={"question": "Who is the opponent's best rated player?"}), config)
    answer = state["messages"][-1]["content"]

    assert _no_leaked_internal_ids(answer)
    assert "'s squad" in answer
