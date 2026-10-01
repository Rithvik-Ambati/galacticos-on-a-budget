"""Builds the LangGraph. docs/DESIGN.md section 10.

Checkpointer: MemorySaver here (in-process, per docs/DECISIONS.md -- no live Postgres
to test a PostgresSaver against in this sandbox). Swapping to
`langgraph.checkpoint.postgres.AsyncPostgresSaver` once Postgres is reachable is a
one-line change at `build_graph`'s call site; nothing about the nodes changes.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncEngine

from graph.nodes import make_nodes
from graph.state import GameState


def build_graph(engine: AsyncEngine, seed: int = 42) -> Any:
    nodes = make_nodes(engine, seed=seed)

    workflow = StateGraph(GameState)
    workflow.add_node("draw", nodes["draw"])
    workflow.add_node("scout", nodes["scout"])
    workflow.add_node("build", nodes["build"])
    workflow.add_node("validate", nodes["validate"])
    workflow.add_node("analyse", nodes["analyse"])
    workflow.add_node("narrate_report", nodes["narrate_report"])
    workflow.add_node("user_decision", nodes["user_decision"])
    workflow.add_node("opponent_counter", nodes["opponent_counter"])
    workflow.add_node("simulate", nodes["simulate"])
    workflow.add_node("narrate_match", nodes["narrate_match"])
    workflow.add_node("chat", nodes["chat"])

    workflow.add_edge(START, "draw")
    workflow.add_edge("draw", "scout")
    workflow.add_edge("scout", "build")
    workflow.add_edge("build", "validate")
    workflow.add_conditional_edges("validate", nodes["validate_router"], {"build": "build", "analyse": "analyse"})
    workflow.add_edge("analyse", "narrate_report")
    workflow.add_edge("narrate_report", "user_decision")
    workflow.add_conditional_edges(
        "user_decision", nodes["decision_router"], {"opponent_counter": "opponent_counter", "simulate": "simulate"}
    )
    workflow.add_edge("opponent_counter", "analyse")
    workflow.add_edge("simulate", "narrate_match")
    workflow.add_edge("narrate_match", "chat")
    workflow.add_conditional_edges("chat", nodes["chat_router"], {"chat": "chat", "__end__": END})

    return workflow.compile(checkpointer=MemorySaver())
