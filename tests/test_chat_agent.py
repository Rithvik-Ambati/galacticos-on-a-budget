"""Unit tests for llm/chat_agent.py's real tool-calling agent loop. No real
Anthropic key exists in CI, so every test drives the loop with a fake provider
(same pattern as tests/test_observability.py's _FakeClient) that returns scripted
Anthropic-shaped Message objects -- this exercises the loop's own logic (tool
dispatch, numeric/leak safety checks, retry-then-fallback) against the real,
fixture-seeded database, not a mocked one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pytest
from langgraph.types import Command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ["DATA_SOURCE"] = "synthetic"

from engine.optimizer import find_optimal_lineup  # noqa: E402
from graph.graph import build_graph  # noqa: E402
from llm.chat_agent import (  # noqa: E402
    MAX_TOOL_ROUNDS,
    _harvest_numbers,
    _tool_query_stats,
    build_session_summary,
    run_chat_agent,
)
from llm.provider import StubProvider  # noqa: E402
from pipeline.features import compute_features  # noqa: E402
from pipeline.ingest import run_ingest  # noqa: E402
from pipeline.pricing import compute_prices  # noqa: E402
from pipeline.team_profiles import compute_team_profiles  # noqa: E402
from pipeline.to_engine import load_candidate_pool, load_squad_player_ids  # noqa: E402

SEED = 42


@dataclass
class _FakeBlock:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] | None = None

    def model_dump(self) -> dict[str, Any]:
        return {"type": self.type, "text": self.text, "id": self.id, "name": self.name, "input": self.input}


@dataclass
class _FakeMessage:
    content: list[_FakeBlock]


class _FakeToolCallingProvider:
    """Implements both Provider.complete (StubProvider's identity function, for
    the fallback path's own call into answer_question) and
    ToolCallingProvider.complete_with_tools (scripted responses, one per call)."""

    def __init__(self, responses: list[_FakeMessage]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 600) -> str:
        return StubProvider().complete(prompt, system=system, max_tokens=max_tokens)

    def complete_with_tools(self, *, system: str, messages: list[Any], tools: list[Any], max_tokens: int = 1024) -> Any:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if not self._responses:
            raise AssertionError("fake provider ran out of scripted responses")
        return self._responses.pop(0)


@pytest.fixture
async def ready_engine(tmp_path):
    db_path = tmp_path / "chat_agent_test.db"
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
async def locked_in_state(ready_engine):
    """A real, fully-built GameState dict (lineup locked in, match simulated) --
    not driven through the StubProvider-routed graph chat node, so each test can
    call llm/chat_agent.py's functions directly with its own fake provider."""
    graph = build_graph(ready_engine, seed=SEED)
    config = {"configurable": {"thread_id": "chat-agent-it"}}

    state = await graph.ainvoke({"mode": "wc", "session_id": "chat-agent-it"}, config)
    opponent_team_id = state["opponent_team_id"]
    assignments = await _optimal_assignments(ready_engine, opponent_team_id)
    state = await graph.ainvoke(Command(resume={"formation": "4-3-3", "assignments": assignments}), config)
    state = await graph.ainvoke(Command(resume={"decision": "lock_in"}), config)
    assert state.get("simulation") is not None
    return ready_engine, dict(state)


def test_harvest_numbers_includes_percentage_form() -> None:
    allowed: set[float] = set()
    _harvest_numbers({"win_pct_fraction": 0.655, "goals": 3}, allowed)
    assert 0.655 in allowed
    assert 65.5 in allowed  # the *100 percentage form
    assert 3.0 in allowed


def test_harvest_numbers_recurses_lists_and_dicts() -> None:
    allowed: set[float] = set()
    _harvest_numbers({"rows": [{"value": 14}, {"value": 10}]}, allowed)
    assert 14.0 in allowed
    assert 10.0 in allowed


async def test_build_session_summary_has_readable_names_not_ids(locked_in_state) -> None:
    engine, state = locked_in_state
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        summary = await build_session_summary(session, state)

    assert len(summary["my_lineup"]) == 11
    for player in summary["my_lineup"]:
        assert "player_id" not in player
        assert player["name"]
    assert summary["opponent_name"] and not summary["opponent_name"].startswith("nt_")
    assert summary["rating"]["overall"] == state["analysis"]["rating"]["overall"]


async def test_tool_query_stats_scopes_to_mine(locked_in_state) -> None:
    engine, state = locked_in_state
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    from graph.chat_tools import get_session_state

    async with session_factory() as session:
        ctx = await get_session_state(session, state)
        result = await _tool_query_stats(session, state, ctx, {"stat": "ability", "scope": "mine"})

    assert "rows" in result
    my_names = {row["name"] for row in result["rows"]}
    assert my_names  # non-empty
    # every returned name must belong to the user's own XI, not the global pool
    from pipeline.to_engine import load_player_card

    async with session_factory() as session:
        my_card_names = set()
        for pid in state["lineup_assignments"].values():
            card = await load_player_card(session, pid)
            if card is not None:
                my_card_names.add(card.name)
    assert my_names <= my_card_names


async def test_agent_happy_path_uses_tool_then_answers(locked_in_state) -> None:
    engine, state = locked_in_state
    overall = state["analysis"]["rating"]["overall"]
    provider = _FakeToolCallingProvider(
        [
            _FakeMessage([_FakeBlock(type="tool_use", id="t1", name="get_session_state", input={})]),
            _FakeMessage([_FakeBlock(type="text", text=f"Your overall rating is {overall:.1f}.")]),
        ]
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        answer, debug = await run_chat_agent(session, "what's my rating?", state, provider)

    assert answer == f"Your overall rating is {overall:.1f}."
    assert debug["used_fallback"] is False
    assert debug["validator_passed"] is True
    assert debug["tools_called"] == [{"name": "get_session_state", "input": {}}]


async def test_agent_falls_back_after_exhausting_tool_rounds(locked_in_state) -> None:
    engine, state = locked_in_state
    # every round calls a tool and never produces text -- forces the round-limit fallback
    responses = [
        _FakeMessage([_FakeBlock(type="tool_use", id=f"t{i}", name="get_postmatch", input={})])
        for i in range(MAX_TOOL_ROUNDS)
    ]
    provider = _FakeToolCallingProvider(responses)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        answer, debug = await run_chat_agent(session, "why did we win?", state, provider)

    assert answer  # the rule-based fallback always returns something
    assert debug["used_fallback"] is True
    assert debug["fallback_reason"] == "tool_round_limit"


async def test_agent_falls_back_when_answer_leaks_a_tool_name(locked_in_state) -> None:
    engine, state = locked_in_state
    leaking_text = "I can test that with simulate_what_if if you want."
    provider = _FakeToolCallingProvider(
        [
            _FakeMessage([_FakeBlock(type="text", text=leaking_text)]),
            _FakeMessage([_FakeBlock(type="text", text=leaking_text)]),  # retry still leaks
        ]
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        answer, debug = await run_chat_agent(session, "could I improve my squad?", state, provider)

    assert "simulate_what_if" not in answer
    assert debug["used_fallback"] is True
    assert debug["fallback_reason"] == "safety_check_failed"


async def test_agent_retries_once_on_ungrounded_number_then_succeeds(locked_in_state) -> None:
    engine, state = locked_in_state
    overall = state["analysis"]["rating"]["overall"]
    provider = _FakeToolCallingProvider(
        [
            _FakeMessage([_FakeBlock(type="text", text="Your rating is 999.9, way above average.")]),
            _FakeMessage([_FakeBlock(type="text", text=f"Your rating is {overall:.1f}.")]),
        ]
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        answer, debug = await run_chat_agent(session, "what's my rating?", state, provider)

    assert answer == f"Your rating is {overall:.1f}."
    assert debug["used_fallback"] is False
    assert debug["validator_attempts"] == 2
