"""Chat tools. docs/DESIGN.md section 9.3: query_stats, retrieve, evaluate_swap,
simulate, similar_players. Each is a real, independently callable function (api/ can
expose any of them as its own endpoint, not only through chat).

`answer_question`'s keyword dispatch is a deliberately honest stand-in for real
tool-calling: StubProvider (llm/provider.py) has no reasoning to decide which tool a
free-text question needs, so this picks by keyword instead of pretending to
understand the question. A real Anthropic-backed provider is where actual
tool-calling would replace this dispatcher; the tool functions themselves don't change.

`get_session_state` resolves "my squad"/"my players"/"my team" to the session's own
lineup and the opponent's squad by id, so every downstream tool call can be scoped
correctly instead of silently querying the global player pool or returning whatever
the retriever happened to rank first (the three real bugs behind this module's
original version: unscoped stats, no conversational memory, raw document/internal-id
leakage on the retrieval fallback).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Player, PlayerFeatures, PlayerStatsSeason, Price
from engine.rating import get_default_rating_model
from engine.rules import validate_lineup
from engine.schemas import Lineup
from engine.simulation import simulate_match
from graph.state import ChatMessage, GameState
from llm.provider import Provider
from llm.sql_tool import SqlToolResult, execute_guarded_sql
from observability import traced_span
from pipeline.to_engine import load_player_card, load_squad_player_ids, load_team_name, load_team_profile
from rag.embeddings import Embedder
from rag.rerank import Reranker
from rag.retriever import RetrievalResult
from rag.retriever import retrieve as rag_retrieve

logger = logging.getLogger(__name__)

RATING_MODEL = get_default_rating_model()

CANNED_QUERIES = {
    "top_ability": "SELECT p.name, f.ability_score FROM players p JOIN player_features f "
    "ON f.player_id = p.player_id ORDER BY f.ability_score DESC LIMIT 10",
    "top_price": "SELECT p.name, pr.price_eur FROM players p JOIN prices pr "
    "ON pr.player_id = p.player_id ORDER BY pr.price_eur DESC LIMIT 10",
}


@dataclass
class SessionContext:
    """Everything chat needs to resolve "my"/"mine"/"the opponent" without ever
    showing the user an internal id. Built fresh per question from `GameState` --
    the state already carries all of this, `answer_question` just wasn't reading it."""

    my_player_ids: set[str]
    opponent_player_ids: set[str]
    opponent_team_id: str | None
    opponent_name: str
    formation: str
    simulation: dict[str, Any] | None
    post_match_analysis: dict[str, Any] | None
    messages: list[ChatMessage] = field(default_factory=list)


async def get_session_state(session: AsyncSession, state: GameState) -> SessionContext:
    opponent_team_id = state.get("opponent_team_id")
    opponent_ids: set[str] = set()
    opponent_name = "the opponent"
    if opponent_team_id:
        opponent_ids = await load_squad_player_ids(session, opponent_team_id)
        opponent_name = await load_team_name(session, opponent_team_id)
    return SessionContext(
        my_player_ids=set(state.get("lineup_assignments", {}).values()),
        opponent_player_ids=opponent_ids,
        opponent_team_id=opponent_team_id,
        opponent_name=opponent_name,
        formation=state.get("formation", "4-3-3"),
        simulation=state.get("simulation"),
        post_match_analysis=state.get("post_match_analysis"),
        messages=list(state.get("messages", [])),
    )


_MINE_RE = re.compile(r"\bmy\s+(squad|players?|team|xi|lineup)\b|\bmine\b")
_OPPONENT_RE = re.compile(r"\b(opponent|their\s+squad|their\s+team|rival|the\s+other\s+team)\b")
_GLOBAL_RE = re.compile(
    r"\b(overall|global|whole\s+pool|entire\s+pool|every\s+player|all\s+players"
    r"|everyone|in\s+general|in\s+the\s+world)\b"
)


def resolve_scope(question: str) -> str:
    """"mine" | "opponent" | "global". "my squad"/"mine" always wins even if the
    same sentence also says "overall" (e.g. "from my squad not in overall") --
    checking order matters here, not just presence. Bare questions with no scope
    word at all ("who are the best rated players?") default to "mine": the
    reported bug was exactly this phrasing returning the global pool instead of
    the user's own XI."""
    q = question.lower()
    if _MINE_RE.search(q):
        return "mine"
    if _OPPONENT_RE.search(q):
        return "opponent"
    if _GLOBAL_RE.search(q):
        return "global"
    return "mine"


_STAT_KEYWORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bassists?\b"), "assists"),
    (re.compile(r"\bgoals?\b"), "goals"),
    (re.compile(r"\b(price|expensive|cost)\b"), "price"),
    (re.compile(r"\b(best|top|rated|rating|ability)\b"), "ability"),
)

_STAT_LABELS = {
    "assists": "Most assists",
    "goals": "Most goals",
    "price": "Most expensive players",
    "ability": "Highest-rated players",
}


def classify_stat(question: str) -> str | None:
    q = question.lower()
    for pattern, stat in _STAT_KEYWORDS:
        if pattern.search(q):
            return stat
    return None


def _last_user_stat_topic(messages: list[ChatMessage]) -> str | None:
    """Conversation memory for bare follow-ups like "from my squad not in
    overall" that carry a scope but no topic of their own -- reuse whatever stat
    the user was just asking about."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            topic = classify_stat(msg.get("content", ""))
            if topic:
                return topic
    return None


def _format_stat_value(stat: str, value: Any) -> str:
    if stat == "price":
        return f"EUR{int(value):,}"
    if stat == "ability":
        return f"{float(value):.1f}"
    return str(int(value))


async def _scoped_stat_rows(
    session: AsyncSession, stat: str, player_ids: set[str] | None, limit: int = 5
) -> list[tuple[str, Any]]:
    if player_ids is not None and not player_ids:
        return []

    stmt: Any
    id_col: Any
    order_col: Any
    if stat == "price":
        stmt = select(Player.name, Price.price_eur).join(Price, Price.player_id == Player.player_id)
        id_col, order_col = Price.player_id, Price.price_eur
    elif stat == "ability":
        stmt = select(Player.name, PlayerFeatures.ability_score).join(
            PlayerFeatures, PlayerFeatures.player_id == Player.player_id
        )
        id_col, order_col = PlayerFeatures.player_id, PlayerFeatures.ability_score
    else:
        col = PlayerStatsSeason.assists if stat == "assists" else PlayerStatsSeason.goals
        stmt = select(Player.name, col).join(PlayerStatsSeason, PlayerStatsSeason.player_id == Player.player_id)
        id_col, order_col = PlayerStatsSeason.player_id, col

    if player_ids is not None:
        stmt = stmt.where(id_col.in_(player_ids))
    stmt = stmt.order_by(order_col.desc()).limit(limit)

    with traced_span("chat.stat_query", as_type="tool", input={"stat": stat, "scoped": player_ids is not None}) as span:
        rows: list[tuple[str, Any]] = [tuple(r) for r in (await session.execute(stmt)).all()]
        if span is not None:
            span.update(output={"n_rows": len(rows)})
    return rows


async def _answer_stat_question(session: AsyncSession, ctx: SessionContext, stat: str, scope: str) -> str:
    if scope == "mine":
        ids, scope_label = ctx.my_player_ids, "your XI"
        if not ids:
            return "Lock in your lineup first, then I can tell you about your own players."
    elif scope == "opponent":
        ids, scope_label = ctx.opponent_player_ids, f"{ctx.opponent_name}'s squad"
        if not ids:
            return "I don't have the opponent's squad loaded yet."
    else:
        ids, scope_label = None, "the full player pool"

    rows: list[tuple[str, Any]]
    if scope == "global" and stat in ("ability", "price"):
        result = await query_stats(session, "top_ability" if stat == "ability" else "top_price")
        if not result.ok:
            logger.info("chat stat fallback: reason=sql_error stat=%s detail=%s", stat, result.reason)
            return f"Couldn't run that query: {result.reason}"
        value_key = "ability_score" if stat == "ability" else "price_eur"
        rows = [(str(r["name"]), r[value_key]) for r in result.rows[:5]]
    else:
        rows = await _scoped_stat_rows(session, stat, ids, limit=5)

    if not rows:
        logger.info("chat stat fallback: reason=no_rows stat=%s scope=%s", stat, scope)
        return f"I don't have {stat} data for {scope_label} yet."

    formatted = ", ".join(f"{name} ({_format_stat_value(stat, value)})" for name, value in rows)
    return f"{_STAT_LABELS[stat]} in {scope_label}: {formatted}."


_WHY_RESULT_RE = re.compile(r"\bwhy\b.*\b(win|won|lose|lost|losing|draw|drew|result)\b")


def is_why_result_question(question: str) -> bool:
    return bool(_WHY_RESULT_RE.search(question.lower()))


async def answer_why_result(ctx: SessionContext) -> str:
    sim = ctx.simulation
    if not sim:
        logger.info("chat fallback: reason=no_simulation question_type=why_result")
        return "Play your match out first -- once it's simulated I can walk through why."

    us, them = sim["narrative_score"]
    if sim.get("went_to_penalties") and sim.get("penalty_score"):
        p_us, p_them = sim["penalty_score"]
        result = "won" if p_us > p_them else "lost"
        score_clause = f"{us}-{them} after extra time, {p_us}-{p_them} on penalties"
    else:
        result = "won" if us > them else "lost" if us < them else "drew"
        score_clause = f"{us}-{them}"
    lead = f"You {result} {score_clause} against {ctx.opponent_name}."

    items = (ctx.post_match_analysis or {}).get("items", [])
    highlights = [
        it["description"] for it in items if it.get("outcome") in ("paid_off", "exposed", "unexpectedly_breached")
    ]
    if not highlights:
        logger.info("chat fallback: reason=no_postmatch_highlights question_type=why_result")
        return lead + " I don't have a detailed breakdown beyond the final score."
    return lead + " " + " ".join(highlights[:2])


_INTERNAL_ID_RE = re.compile(r"\b(nt_|club_)\w+", re.IGNORECASE)


async def answer_via_retrieval(session: AsyncSession, question: str, ctx: SessionContext) -> str:
    """Last resort when no keyword/topic branch matched. Never returns a raw
    document verbatim: a doc about an entity outside the resolvable session scope
    (not the user's XI, not the opponent's squad/team) gets an honest fallback
    instead of a leaked out-of-scope profile, and any internal id that slips
    through in-scope text (e.g. "Team nt_3589...") is redacted before it reaches
    the user. Every fallback path is logged with its reason."""
    retrieval = await rag_retrieve(session, question)
    if not retrieval.docs or retrieval.low_relevance:
        logger.info("chat fallback: reason=%s question=%r", "low_relevance" if retrieval.docs else "no_docs", question)
        return (
            "I couldn't find a reliable answer to that -- try asking about a specific player, "
            "your squad's stats, or the match odds."
        )

    doc = retrieval.docs[0]
    entity_id = doc.metadata.get("entity_id")
    doc_type = doc.metadata.get("doc_type")
    in_scope = (
        entity_id is None
        or entity_id in ctx.my_player_ids
        or entity_id in ctx.opponent_player_ids
        or entity_id == ctx.opponent_team_id
    )
    if not in_scope:
        logger.info("chat fallback: reason=out_of_scope_retrieval entity_id=%s question=%r", entity_id, question)
        return (
            "I couldn't find a reliable answer scoped to your squad or the opponent -- "
            "try naming the player directly."
        )

    text = doc.text
    if doc_type == "opponent_report":
        text = _INTERNAL_ID_RE.sub(ctx.opponent_name, text, count=1)
    elif _INTERNAL_ID_RE.search(text):
        logger.info("chat fallback: reason=id_leak_redacted entity_id=%s question=%r", entity_id, question)
        text = _INTERNAL_ID_RE.sub("the opponent", text)
    return text


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
    ctx = await get_session_state(session, state)
    q = question.lower()

    if "similar" in q or "like" in q:
        lineup_ids = list(ctx.my_player_ids)
        if lineup_ids:
            sims = await similar_players(session, lineup_ids[0])
            if sims:
                return "Similar players by playing style: " + ", ".join(
                    f"{s['name']} ({s['similarity']:.2f})" for s in sims
                )
        return "Pick a player in your lineup first, then ask who plays like them."

    if is_why_result_question(q):
        return await answer_why_result(ctx)

    if "simulat" in q or "chance" in q or "odds" in q:
        sim = ctx.simulation
        if sim:
            return f"Simulated: {sim['win_pct']:.1f}% win, {sim['draw_pct']:.1f}% draw, {sim['loss_pct']:.1f}% loss."
        return "Lock in your lineup first and I'll simulate the match."

    stat = classify_stat(q) or _last_user_stat_topic(ctx.messages)
    if stat is not None:
        return await _answer_stat_question(session, ctx, stat, resolve_scope(q))

    return await answer_via_retrieval(session, question, ctx)
