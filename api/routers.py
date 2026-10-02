"""All endpoints. Implements docs/DESIGN.md section 11.

Each session is one LangGraph thread (session_id == thread_id); the graph's own
interrupts (build / user_decision / chat) are what these endpoints resume. Where a
check is cheap, pure and needed before committing to a graph step (lineup validation,
player search), this calls engine/pipeline directly instead of round-tripping the
graph, matching CLAUDE.md's "one place for game rules" without making every read a
graph step.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_graph, get_session
from api.schemas import (
    AnalyseResponse,
    ChatRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    DecisionRequest,
    DecisionResponse,
    DrawResponse,
    LineupSubmitRequest,
    LineupValidateResponse,
    PlayerSearchResponse,
    PlayerSearchResult,
    ScoutingResponse,
    SessionStateResponse,
    SimulateResponse,
)
from db.models import GameSession
from engine.rules import eligibility as engine_eligibility
from engine.rules import validate_lineup
from engine.schemas import Lineup, LineupAnalysis, SimulationResult
from engine.team_profile import press_intensity
from pipeline.to_engine import (
    load_candidate_pool,
    load_player_card,
    load_squad_player_ids,
    load_team_name,
    load_team_profile,
)

router = APIRouter()


def _problem(status: int, title: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"title": title, "detail": detail, "status": status})


def _awaiting(state: dict[str, Any]) -> str | None:
    interrupts = state.get("__interrupt__")
    if not interrupts:
        return None
    value = interrupts[0].value
    return value.get("awaiting") if isinstance(value, dict) else None


def _current_state(graph_: Any, session_id: str) -> dict[str, Any]:
    """The raw LangGraph state snapshot: GameState's own fields plus LangGraph's own
    `__interrupt__` key, which doesn't belong in GameState (it's graph plumbing, not
    game state) -- so this is deliberately `dict[str, Any]`, not `GameState`."""
    config = {"configurable": {"thread_id": session_id}}
    snapshot = graph_.get_state(config)
    return dict(snapshot.values)


async def _get_session_row(session: AsyncSession, session_id: str) -> GameSession:
    row = await session.get(GameSession, session_id)
    if row is None:
        raise _problem(404, "session not found", f"no session {session_id}")
    return row


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest, session: AsyncSession = Depends(get_session)) -> CreateSessionResponse:
    if req.mode not in ("wc", "ucl"):
        raise _problem(400, "invalid mode", "mode must be 'wc' or 'ucl'")
    session_id = uuid.uuid4().hex
    session.add(GameSession(session_id=session_id, mode=req.mode, state={}))
    await session.commit()
    return CreateSessionResponse(session_id=session_id, mode=req.mode)


@router.post("/sessions/{session_id}/draw", response_model=DrawResponse)
async def draw(session_id: str, session: AsyncSession = Depends(get_session)) -> DrawResponse:
    row = await _get_session_row(session, session_id)
    graph_ = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state = await graph_.ainvoke({"mode": row.mode, "session_id": session_id}, config)
    opponent_team_id = state["opponent_team_id"]
    name = await load_team_name(session, opponent_team_id)
    return DrawResponse(
        session_id=session_id, opponent_team_id=opponent_team_id, opponent_name=name,
        awaiting=_awaiting(state) or "lineup",
    )


@router.get("/sessions/{session_id}/scout", response_model=ScoutingResponse)
async def scout(session_id: str, session: AsyncSession = Depends(get_session)) -> ScoutingResponse:
    graph_ = get_graph()
    state = _current_state(graph_, session_id)
    opponent_team_id = state.get("opponent_team_id")
    if not opponent_team_id:
        raise _problem(409, "no opponent yet", "call /draw first")
    profile = await load_team_profile(session, opponent_team_id, opponent_team_id, "4-2-3-1")
    return ScoutingResponse(
        opponent_team_id=opponent_team_id,
        attack_channels=profile.attack_channels,
        press_intensity_ppda=round(press_intensity(profile.ppda), 1),
        crosses_per_match=profile.crosses_per_match,
        set_piece_threat=profile.set_piece_threat,
        aerial=profile.aerial,
        danger_players=[dp.model_dump() for dp in profile.danger_players],
    )


@router.get("/sessions/{session_id}/players/search", response_model=PlayerSearchResponse)
async def search_players(
    session_id: str,
    q: str = Query(default=""),
    position_group: str | None = Query(default=None),
    slot_id: str | None = Query(default=None),
    max_price_eur: int | None = Query(default=None),
    limit: int = Query(default=30, le=100),
    session: AsyncSession = Depends(get_session),
) -> PlayerSearchResponse:
    graph_ = get_graph()
    state = _current_state(graph_, session_id)
    opponent_team_id = state.get("opponent_team_id")
    opponent_ids = await load_squad_player_ids(session, opponent_team_id) if opponent_team_id else set()

    pool = await load_candidate_pool(session, exclude_ids=set(), position_group=position_group, limit=400)
    if q:
        pool = [p for p in pool if q.lower() in p.name.lower()]
    if max_price_eur is not None:
        # still ability-sorted (load_candidate_pool's own order), just capped to what's
        # affordable -- without this, a tight budget can never find anything to show,
        # since the top-400-by-ability pool skews toward expensive players.
        pool = [p for p in pool if p.price_eur <= max_price_eur]
    pool = pool[:limit]

    formation = state.get("formation", "4-3-3")
    cards = {}
    for sid, pid in state.get("lineup_assignments", {}).items():
        card = await load_player_card(session, pid)
        if card is not None:
            cards[sid] = card
    lineup = Lineup(formation=formation, assignments=cards)

    results = [
        PlayerSearchResult(player=p, eligibility=engine_eligibility(p, lineup, opponent_ids, slot_id=slot_id))
        for p in pool
    ]
    return PlayerSearchResponse(results=results)


@router.post("/sessions/{session_id}/lineup/validate", response_model=LineupValidateResponse)
async def validate_lineup_endpoint(
    session_id: str, req: LineupSubmitRequest, session: AsyncSession = Depends(get_session)
) -> LineupValidateResponse:
    graph_ = get_graph()
    state = _current_state(graph_, session_id)
    opponent_team_id = state.get("opponent_team_id")
    opponent_ids = await load_squad_player_ids(session, opponent_team_id) if opponent_team_id else set()

    cards = {}
    for slot_id, pid in req.assignments.items():
        card = await load_player_card(session, pid)
        if card is not None:
            cards[slot_id] = card
    lineup = Lineup(formation=req.formation, assignments=cards)
    result = validate_lineup(lineup, opponent_ids, require_complete=False)
    return LineupValidateResponse(
        valid=result.valid, violations=[v.message for v in result.violations],
        budget_spent_eur=result.budget_spent_eur, budget_left_eur=result.budget_left_eur,
        nationality_counts=result.nationality_counts, filled_slots=result.filled_slots,
    )


@router.post("/sessions/{session_id}/lineup/analyse", response_model=AnalyseResponse)
async def analyse_lineup(
    session_id: str, req: LineupSubmitRequest, session: AsyncSession = Depends(get_session)
) -> AnalyseResponse:
    graph_ = get_graph()
    state = _current_state(graph_, session_id)
    opponent_team_id = state.get("opponent_team_id")
    if not opponent_team_id:
        raise _problem(409, "no opponent yet", "call /draw first")

    opponent_ids = await load_squad_player_ids(session, opponent_team_id)
    cards = {}
    for slot_id, pid in req.assignments.items():
        card = await load_player_card(session, pid)
        if card is not None:
            cards[slot_id] = card
    lineup = Lineup(formation=req.formation, assignments=cards)
    pre_check = validate_lineup(lineup, opponent_ids)
    if not pre_check.valid:
        raise _problem(422, "lineup invalid", "; ".join(v.message for v in pre_check.violations))

    config = {"configurable": {"thread_id": session_id}}
    new_state = await graph_.ainvoke(Command(resume={"formation": req.formation, "assignments": req.assignments}), config)
    if new_state.get("analysis") is None:
        raise _problem(422, "lineup invalid", "the engine rejected this lineup")

    return AnalyseResponse(
        analysis=LineupAnalysis.model_validate(new_state["analysis"]),
        coach_report_text=new_state.get("coach_report_text", ""),
        awaiting=_awaiting(new_state) or "decision",
    )


@router.post("/sessions/{session_id}/decision", response_model=DecisionResponse)
async def decision(session_id: str, req: DecisionRequest, session: AsyncSession = Depends(get_session)) -> DecisionResponse:
    if req.decision not in ("counter", "lock_in"):
        raise _problem(400, "invalid decision", "decision must be 'counter' or 'lock_in'")
    graph_ = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state = await graph_.ainvoke(Command(resume={"decision": req.decision}), config)

    awaiting = _awaiting(state) or ""
    counter_history = state.get("counter_history", [])
    return DecisionResponse(
        awaiting=awaiting,
        counter_round=state.get("counter_round"),
        last_counter_round=counter_history[-1] if req.decision == "counter" and counter_history else None,
        analysis=LineupAnalysis.model_validate(state["analysis"]) if state.get("analysis") else None,
        coach_report_text=state.get("coach_report_text"),
        simulation=SimulationResult.model_validate(state["simulation"]) if state.get("simulation") else None,
        match_report_text=state.get("match_report_text"),
    )


@router.post("/sessions/{session_id}/simulate", response_model=SimulateResponse)
async def simulate_endpoint(session_id: str) -> SimulateResponse:
    graph_ = get_graph()
    state = _current_state(graph_, session_id)
    if not state.get("simulation"):
        raise _problem(409, "not locked in", "call POST .../decision with lock_in first")
    return SimulateResponse(
        simulation=SimulationResult.model_validate(state["simulation"]),
        match_report_text=state.get("match_report_text", ""),
    )


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: str, req: ChatRequest) -> StreamingResponse:
    graph_ = get_graph()
    config = {"configurable": {"thread_id": session_id}}

    async def event_stream() -> AsyncIterator[str]:
        state = await graph_.ainvoke(Command(resume={"question": req.question}), config)
        answer = state["messages"][-1]["content"] if state.get("messages") else ""
        for word in answer.split(" "):
            yield f"data: {json.dumps({'token': word + ' '})}\n\n"
            await asyncio.sleep(0.02)
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/sessions/{session_id}/chat/end")
async def end_chat(session_id: str) -> dict[str, bool]:
    graph_ = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    await graph_.ainvoke(Command(resume={"end": True}), config)
    return {"ended": True}


@router.get("/sessions/{session_id}", response_model=SessionStateResponse)
async def get_session_state(session_id: str, session: AsyncSession = Depends(get_session)) -> SessionStateResponse:
    await _get_session_row(session, session_id)  # 404s if unknown
    graph_ = get_graph()
    state = _current_state(graph_, session_id)
    return SessionStateResponse(
        session_id=session_id,
        mode=state.get("mode", ""),
        opponent_team_id=state.get("opponent_team_id"),
        formation=state.get("formation"),
        lineup_assignments=state.get("lineup_assignments", {}),
        counter_round=state.get("counter_round", 0),
        awaiting=_awaiting(state),
        analysis=LineupAnalysis.model_validate(state["analysis"]) if state.get("analysis") else None,
        simulation=SimulationResult.model_validate(state["simulation"]) if state.get("simulation") else None,
        messages=state.get("messages", []),
    )
