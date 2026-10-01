"""Templated player profiles and opponent reports, embedded incrementally.

Implements docs/DESIGN.md section 8. Documents are built from engine/pipeline numbers
only -- the LLM never invents a stat here, it just gets handed well-formatted prose to
retrieve later (CLAUDE.md rule 1).
"""

from __future__ import annotations

import datetime as dt
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Document, Player, PlayerFeatures, PlayerStatsSeason, Price
from db.models import TeamProfile as TeamProfileRow
from pipeline.features import _group, compute_role_fit
from rag.embeddings import Embedder


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _player_profile_text(player: Player, features: PlayerFeatures, stats: PlayerStatsSeason, price: Price | None) -> str:
    group = _group(player)
    role_fit = compute_role_fit(features.role_percentiles)
    best_role = max(role_fit.items(), key=lambda kv: kv[1])[0].replace("_", " ") if role_fit else "generalist"
    confidence_note = (
        "Stats confidence is low -- limited detailed coverage for this player."
        if features.confidence < 0.8
        else "Stats confidence is high."
    )
    price_note = f"Priced at EUR{price.price_eur:,} for the current tournament snapshot." if price else "Not yet priced."

    age = int((dt.date.today() - player.dob).days / 365.25) if player.dob else None
    age_clause = f", age {age}" if age is not None else ""
    lines = [
        f"{player.name} is a {group} ({', '.join(player.positions)}) from {player.nationality}{age_clause}.",
        f"Ability score: {features.ability_score:.1f}/100. Best-fit role: {best_role}.",
        f"Season {stats.season}: {stats.minutes} minutes, {stats.goals} goals, {stats.assists} assists "
        f"(xG {stats.xg:.1f}, xA {stats.xa:.1f}).",
        f"Pass completion {stats.pass_completion:.0f}%, {stats.tackles_won} tackles won, "
        f"{stats.progressive_carries} progressive carries.",
        confidence_note,
        price_note,
    ]
    return " ".join(lines)


def _opponent_report_text(team: TeamProfileRow, player_names: dict[str, str]) -> str:
    danger = ", ".join(
        f"{player_names.get(str(dp.get('player_id', '')), str(dp.get('name', '?')))} ({dp.get('note', '')})"
        for dp in team.danger_players
    ) if team.danger_players else "no standout individual threats logged"

    lines = [
        f"Team {team.team_id}, snapshot {team.snapshot}.",
        f"Attacking emphasis: left {team.attack_channels.get('left', 0):.0f}%, "
        f"center {team.attack_channels.get('center', 0):.0f}%, right {team.attack_channels.get('right', 0):.0f}%.",
        f"PPDA {team.ppda:.1f} (press intensity). {team.crosses_per_match:.1f} crosses per match. "
        f"Set-piece threat {team.set_piece_threat:.0f}/100. Aerial threat {team.aerial:.0f}/100.",
        f"Key threats: {danger}.",
    ]
    return " ".join(lines)


async def build_player_documents(session: AsyncSession, embed_model: str, embedder: Embedder | None) -> int:
    rows = (
        await session.execute(
            select(Player, PlayerFeatures, PlayerStatsSeason, Price)
            .join(PlayerFeatures, PlayerFeatures.player_id == Player.player_id)
            .join(PlayerStatsSeason, PlayerStatsSeason.player_id == Player.player_id)
            .outerjoin(Price, Price.player_id == Player.player_id)
        )
    ).all()

    written = 0
    for player, features, stats, price in rows:
        text = _player_profile_text(player, features, stats, price)
        content_hash = _content_hash(text)
        doc_id = f"player_profile:{player.player_id}"

        existing = await session.get(Document, doc_id)
        if existing is not None and existing.content_hash == content_hash:
            continue  # unchanged since last embed -- incremental, per DESIGN section 8

        embedding = embedder(text) if embedder is not None else None
        metadata = {
            "entity_id": player.player_id,
            "doc_type": "player_profile",
            "position": player.positions[0] if player.positions else None,
            "nationality": player.nationality,
            "price": price.price_eur if price else None,
            "season": stats.season,
        }
        await session.merge(
            Document(
                doc_id=doc_id,
                doc_type="player_profile",
                entity_id=player.player_id,
                text=text,
                metadata_json=metadata,
                embedding=embedding,
                content_hash=content_hash,
                embed_model=embed_model if embedding is not None else None,
            )
        )
        written += 1

    await session.commit()
    return written


async def build_opponent_documents(session: AsyncSession, embed_model: str, embedder: Embedder | None) -> int:
    teams = (await session.execute(select(TeamProfileRow))).scalars().all()
    player_names = {p.player_id: p.name for p in (await session.execute(select(Player))).scalars().all()}

    written = 0
    for team in teams:
        text = _opponent_report_text(team, player_names)
        content_hash = _content_hash(text)
        doc_id = f"opponent_report:{team.team_id}:{team.snapshot}"

        existing = await session.get(Document, doc_id)
        if existing is not None and existing.content_hash == content_hash:
            continue

        embedding = embedder(text) if embedder is not None else None
        metadata = {"entity_id": team.team_id, "doc_type": "opponent_report", "season": team.snapshot}
        await session.merge(
            Document(
                doc_id=doc_id,
                doc_type="opponent_report",
                entity_id=team.team_id,
                text=text,
                metadata_json=metadata,
                embedding=embedding,
                content_hash=content_hash,
                embed_model=embed_model if embedding is not None else None,
            )
        )
        written += 1

    await session.commit()
    return written
