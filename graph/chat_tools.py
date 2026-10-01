"""Chat tools. docs/DESIGN.md section 9.3: query_stats, retrieve, evaluate_swap,
simulate, similar_players. Each is a real, independently callable function (api/ can
expose any of them as its own endpoint, not only through chat).

`answer_question`'s keyword dispatch is a deliberately honest stand-in for real
tool-calling: StubProvider (llm/provider.py) has no reasoning to decide which tool a
free-text question needs, so this picks by keyword instead of pretending to
understand the question. A real Anthropic-backed provider is where actual
tool-calling would replace this dispatcher; the tool functions themselves don't change.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Player, PlayerFeatures
from engine.rating import get_default_rating_model
from engine.rules import validate_lineup
from engine.schemas import Lineup
from engine.simulation import simulate_match
from graph.state import GameState
from llm.provider import Provider
from llm.sql_tool import SqlToolResult, execute_guarded_sql
from pipeline.to_engine import load_player_card, load_squad_player_ids, load_team_profile
from rag.embeddings import Embedder
from rag.rerank import Reranker
from rag.retriever import RetrievalResult
from rag.retriever import retrieve as rag_retrieve

RATING_MODEL = get_default_rating_model()

CANNED_QUERIES = {
    "top_ability": "SELECT p.name, f.ability_score FROM players p JOIN player_features f "
    "ON f.player_id = p.player_id ORDER BY f.ability_score DESC LIMIT 10",
    "top_price": "SELECT p.name, pr.price_eur FROM players p JOIN prices pr "
    "ON pr.player_id = p.player_id ORDER BY pr.price_eur DESC LIMIT 10",
}


async def query_stats(session: AsyncSession, intent: str) -> SqlToolResult:
    """intent: "top_ability" | "top_price" -- see CANNED_QUERIES. A real NL-to-SQL
    model would translate free text here; llm/sql_tool.py's guardrails apply either
    way (allowlist, SELECT-only, timeout, row limit)."""
    sql = CANNED_QUERIES.get(intent, CANNED_QUERIES["top_ability"])
    return await execute_guarded_sql(session, sql)


async def retrieve(
    session: AsyncSession, question: str, embedder: Embedder | None = None, reranker: Reranker | None = None
) -> RetrievalResult:
    return await rag_retrieve(session, question, embedder=embedder, reranker=reranker)


async def evaluate_swap(
    session: AsyncSession, state: GameState, out_slot: str, in_player_id: str
) -> dict[str, object]:
    assignments = dict(state.get("lineup_assignments", {}))
    if out_slot not in assignments:
        return {"ok": False, "reason": f"no player currently in slot {out_slot}"}

    formation = state.get("formation", "4-3-3")
    opponent_ids = await load_squad_player_ids(session, state["opponent_team_id"])
    in_card = await load_player_card(session, in_player_id)
    if in_card is None:
        return {"ok": False, "reason": f"unknown player {in_player_id}"}

    cards = {}
    for slot_id, pid in assignments.items():
        card = await load_player_card(session, pid)
        if card is not None:
            cards[slot_id] = card
    before_lineup = Lineup(formation=formation, assignments=cards)
    after_lineup = Lineup(formation=formation, assignments={**cards, out_slot: in_card})

    validation = validate_lineup(after_lineup, opponent_ids, require_complete=False)
    if not validation.valid:
        return {"ok": False, "reason": "; ".join(v.message for v in validation.violations)}

    opponent_profile = await load_team_profile(
        session, state["opponent_team_id"], state["opponent_team_id"], "4-2-3-1"
    )
    before_rating = RATING_MODEL.rate(before_lineup, opponent_profile).overall
    after_rating = RATING_MODEL.rate(after_lineup, opponent_profile).overall
    return {
        "ok": True, "rating_before": before_rating, "rating_after": after_rating,
        "rating_gain": round(after_rating - before_rating, 1),
    }


async def simulate(session: AsyncSession, state: GameState) -> dict[str, object]:
    assignments = {}
    for slot_id, pid in state.get("lineup_assignments", {}).items():
        card = await load_player_card(session, pid)
        if card is not None:
            assignments[slot_id] = card
    lineup = Lineup(formation=state.get("formation", "4-3-3"), assignments=assignments)
    opponent_profile = await load_team_profile(session, state["opponent_team_id"], state["opponent_team_id"], "4-2-3-1")
    rating = RATING_MODEL.rate(lineup, opponent_profile)
    result = simulate_match(rating, lineup, opponent_profile)
    return result.model_dump()


async def similar_players(session: AsyncSession, player_id: str, top_k: int = 5) -> list[dict[str, object]]:
    target = await session.get(PlayerFeatures, {"player_id": player_id, "snapshot": "2026"})
    if target is None or not target.style_vector:
        return []
    target_vec = np.array(target.style_vector)
    target_norm = target_vec / (np.linalg.norm(target_vec) or 1.0)

    others = (await session.execute(select(PlayerFeatures).where(PlayerFeatures.player_id != player_id))).scalars().all()
    names = {p.player_id: p.name for p in (await session.execute(select(Player))).scalars().all()}

    scored = []
    for f in others:
        if not f.style_vector:
            continue
        v = np.array(f.style_vector)
        v_norm = v / (np.linalg.norm(v) or 1.0)
        scored.append((f.player_id, float(np.dot(target_norm, v_norm))))
    scored.sort(key=lambda t: -t[1])
    return [{"player_id": pid, "name": names.get(pid, pid), "similarity": round(score, 3)} for pid, score in scored[:top_k]]


async def answer_question(session: AsyncSession, question: str, state: GameState, provider: Provider) -> str:
    q = question.lower()

    if "similar" in q or "like" in q:
        lineup_ids = list(state.get("lineup_assignments", {}).values())
        if lineup_ids:
            sims = await similar_players(session, lineup_ids[0])
            if sims:
                return "Similar players by playing style: " + ", ".join(
                    f"{s['name']} ({s['similarity']:.2f})" for s in sims
                )
        return "Pick a player in your lineup first, then ask who plays like them."

    if "price" in q or "expensive" in q or "cost" in q:
        result = await query_stats(session, "top_price")
        if result.ok:
            return "Most expensive players right now: " + ", ".join(
                f"{r['name']} (EUR{r['price_eur']:,})" for r in result.rows[:5]
            )
        return f"Couldn't run that query: {result.reason}"

    if "best" in q or "top" in q or "rated" in q:
        result = await query_stats(session, "top_ability")
        if result.ok:
            return "Highest-rated players right now: " + ", ".join(
                f"{r['name']} ({r['ability_score']:.1f})" for r in result.rows[:5]
            )
        return f"Couldn't run that query: {result.reason}"

    if "simulat" in q or "chance" in q or "odds" in q:
        sim = state.get("simulation")
        if sim:
            return f"Simulated: {sim['win_pct']:.1f}% win, {sim['draw_pct']:.1f}% draw, {sim['loss_pct']:.1f}% loss."
        return "Lock in your lineup first and I'll simulate the match."

    retrieval = await retrieve(session, question)
    if retrieval.docs and not retrieval.low_relevance:
        return retrieval.docs[0].text
    return "I don't have enough data to answer that confidently yet."
