"""LangGraph state. docs/DESIGN.md section 10.

Kept to primitives/dicts (not engine Pydantic objects) because LangGraph persists this
through its checkpointer on every step -- node functions re-hydrate engine objects
from the DB by id each time they need them (graph/nodes.py).
"""

from __future__ import annotations

from typing import TypedDict


class ChatMessage(TypedDict):
    role: str  # "user" | "assistant"
    content: str


class ResumeMismatch(Exception):
    """Raised when a graph node's resume payload doesn't match the interrupt it's
    answering -- e.g. the API resumed the "decision" interrupt while the thread was
    actually still paused at "lineup". Without this, the node's own `payload["key"]`
    lookup raises a bare KeyError that reaches the client as an opaque 500 (or, from
    inside chat()'s streaming generator, as a silently empty response), and leaves the
    thread's checkpoint stuck needing a fresh session. api/routers.py catches this and
    returns a 409 instead.
    """

    def __init__(self, expected: str, payload: dict[str, object]) -> None:
        super().__init__(f"expected a resume payload for {expected!r}, got {payload!r}")
        self.expected = expected


class GameState(TypedDict, total=False):
    mode: str  # "wc" | "ucl"
    session_id: str
    fixed_opponent_team_id: str | None  # rematch: skip the random draw, pin this opponent
    opponent_team_id: str
    opponent_formation: str
    opponent_lineup_assignments: dict[str, str]  # slot_id -> player_id, opponent's XI
    opponent_out_of_position: list[dict[str, object]]  # Part 2b: thin-squad fallback fills
    opponent_lineup_source: str  # Part 2c: "real" (frequency-backed) | "estimated"
    formation: str
    lineup_assignments: dict[str, str]  # slot_id -> player_id, the user's XI
    budget_left_eur: int
    nationality_counts: dict[str, int]
    validation_ok: bool
    analysis: dict[str, object] | None
    counter_round: int
    counter_history: list[dict[str, object]]
    decision: str | None  # "counter" | "lock_in"
    simulation: dict[str, object] | None
    man_of_the_match: dict[str, object] | None
    post_match_analysis: dict[str, object] | None
    coach_report_text: str | None
    match_report_text: str | None
    messages: list[ChatMessage]
    _chat_ended: bool
