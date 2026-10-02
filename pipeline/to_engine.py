"""Converts persisted rows into the engine's Pydantic schemas. The one bridge module
between db/ (storage) and engine/ (pure logic) -- engine/ itself never imports db/,
keeping CLAUDE.md's "engine code must not import from llm/ or api/" boundary (and the
same boundary against db/) intact.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Club, NationalTeam, Player, PlayerFeatures, PlayerStatsSeason, Price, Squad, TeamLineupFrequency
from db.models import TeamProfile as TeamProfileRow
from engine.schemas import DangerPlayer, PlayerCard
from engine.schemas import TeamProfile as EngineTeamProfile
from pipeline.features import _group, _per90, compute_role_fit


def _as_float(value: object) -> float:
    return float(value) if isinstance(value, (int, float, str)) else 0.0


def _to_player_card(
    player: Player, features: PlayerFeatures, stats: PlayerStatsSeason, price: Price | None
) -> PlayerCard:
    return PlayerCard(
        player_id=player.player_id,
        name=player.name,
        nationality=player.nationality,
        position_group=_group(player),
        position_code=player.positions[0] if player.positions else "CM",
        ability_score=features.ability_score,
        price_eur=price.price_eur if price else 1_000_000,
        confidence=features.confidence,
        role_fit=compute_role_fit(features.role_percentiles),
        per90=_per90(stats),
        preferred_foot=player.preferred_foot,
        natural_position_codes=list(player.positions),
    )


async def load_player_card(session: AsyncSession, player_id: str, snapshot: str = "2026") -> PlayerCard | None:
    row = (
        await session.execute(
            select(Player, PlayerFeatures, PlayerStatsSeason, Price)
            .join(PlayerFeatures, PlayerFeatures.player_id == Player.player_id)
            .join(PlayerStatsSeason, PlayerStatsSeason.player_id == Player.player_id)
            .outerjoin(Price, (Price.player_id == Player.player_id) & (Price.tournament_snapshot == snapshot))
            .where(Player.player_id == player_id)
        )
    ).first()
    if row is None:
        return None
    return _to_player_card(*row)


async def load_candidate_pool(
    session: AsyncSession,
    *,
    exclude_ids: set[str] | None = None,
    position_group: str | None = None,
    snapshot: str = "2026",
    limit: int = 400,
) -> list[PlayerCard]:
    stmt = (
        select(Player, PlayerFeatures, PlayerStatsSeason, Price)
        .join(PlayerFeatures, PlayerFeatures.player_id == Player.player_id)
        .join(PlayerStatsSeason, PlayerStatsSeason.player_id == Player.player_id)
        .outerjoin(Price, (Price.player_id == Player.player_id) & (Price.tournament_snapshot == snapshot))
        .order_by(PlayerFeatures.ability_score.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    cards = [_to_player_card(*row) for row in rows]
    if exclude_ids:
        cards = [c for c in cards if c.player_id not in exclude_ids]
    if position_group:
        cards = [c for c in cards if c.position_group == position_group]
    return cards


async def load_team_name(session: AsyncSession, team_id: str) -> str:
    """Display name for a team_id (e.g. "nt_ENG" -> "ENG") -- narration should never
    show the internal id to the user."""
    if team_id.startswith("nt_"):
        national = await session.get(NationalTeam, team_id)
        return national.name if national else team_id
    club = await session.get(Club, team_id)
    return club.name if club else team_id


async def load_squad_player_ids(session: AsyncSession, team_id: str) -> set[str]:
    rows = (await session.execute(select(Squad.player_id).where(Squad.team_id == team_id))).scalars().all()
    return set(rows)


async def load_squad_player_cards(session: AsyncSession, team_id: str, snapshot: str = "2026") -> list[PlayerCard]:
    ids = await load_squad_player_ids(session, team_id)
    return [c for pid in ids if (c := await load_player_card(session, pid, snapshot)) is not None]


async def load_lineup_frequency(session: AsyncSession, team_id: str) -> dict[tuple[str, str], int]:
    """Part 2c: empty for synthetic data or any team with no real match history --
    engine/opponent_lineup.py falls back to its ability-only builder either way."""
    rows = (
        await session.execute(
            select(TeamLineupFrequency.player_id, TeamLineupFrequency.position_code, TeamLineupFrequency.start_count)
            .where(TeamLineupFrequency.team_id == team_id)
        )
    ).all()
    return {(player_id, position_code): count for player_id, position_code, count in rows}


async def load_team_profile(
    session: AsyncSession, team_id: str, team_name: str, formation: str, snapshot: str = "2026"
) -> EngineTeamProfile:
    row = await session.get(TeamProfileRow, {"team_id": team_id, "snapshot": snapshot})
    if row is None:
        raise ValueError(
            f"no team_profiles row for {team_id!r} at snapshot {snapshot!r} -- run pipeline.team_profiles first"
        )
    return EngineTeamProfile(
        team_id=row.team_id,
        name=team_name,
        formation=formation,
        attack_channels=row.attack_channels,
        ppda=row.ppda,
        crosses_per_match=row.crosses_per_match,
        set_piece_threat=row.set_piece_threat,
        aerial=row.aerial,
        danger_players=[
            DangerPlayer(
                player_id=str(dp.get("player_id", "")), name=str(dp.get("name", "?")),
                position_code=str(dp.get("position_code", "")),
                ability_score=_as_float(dp.get("ability_score", 0.0)), note=str(dp.get("note", "")),
            )
            for dp in row.danger_players
        ],
    )
