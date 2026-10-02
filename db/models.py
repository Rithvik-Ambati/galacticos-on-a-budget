"""Core tables. Implements docs/DESIGN.md section 6.

Every model that crosses a module boundary is re-exposed as a Pydantic model
elsewhere (CLAUDE.md convention); these are persistence-only.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from db.vector_type import VectorType

EMBEDDING_DIM = 384
STYLE_VECTOR_DIM = 16


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    dob: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    nationality: Mapped[str] = mapped_column(String(64))
    positions: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_foot: Mapped[str] = mapped_column(String(8), default="right")
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_club_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("clubs.club_id"), nullable=True
    )


class PlayerIdMap(Base):
    __tablename__ = "player_id_map"

    player_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("players.player_id"), primary_key=True
    )
    tm_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    understat_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    statsbomb_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    match_method: Mapped[str] = mapped_column(String(32))
    match_score: Mapped[float] = mapped_column(Float)


class Club(Base):
    __tablename__ = "clubs"

    club_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(64))
    competition: Mapped[str] = mapped_column(String(64))


class NationalTeam(Base):
    __tablename__ = "national_teams"

    team_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(64))
    competition: Mapped[str] = mapped_column(String(64))


class Squad(Base):
    __tablename__ = "squads"

    squad_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(32), index=True)
    team_type: Mapped[str] = mapped_column(String(16))  # club | national
    tournament: Mapped[str] = mapped_column(String(32), index=True)  # WC2026 | UCL2026
    player_id: Mapped[str] = mapped_column(String(32), ForeignKey("players.player_id"), index=True)


class PlayerStatsSeason(Base):
    __tablename__ = "player_stats_season"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    player_id: Mapped[str] = mapped_column(String(32), ForeignKey("players.player_id"), index=True)
    season: Mapped[str] = mapped_column(String(16))
    competition: Mapped[str] = mapped_column(String(64))
    minutes: Mapped[int] = mapped_column(Integer)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    xg: Mapped[float] = mapped_column(Float, default=0.0)
    xa: Mapped[float] = mapped_column(Float, default=0.0)
    shots: Mapped[int] = mapped_column(Integer, default=0)
    key_passes: Mapped[int] = mapped_column(Integer, default=0)
    tackles_won: Mapped[int] = mapped_column(Integer, default=0)
    dribbled_past: Mapped[int] = mapped_column(Integer, default=0)
    aerials_won: Mapped[int] = mapped_column(Integer, default=0)
    aerials_total: Mapped[int] = mapped_column(Integer, default=0)
    progressive_carries: Mapped[int] = mapped_column(Integer, default=0)
    take_ons_won: Mapped[int] = mapped_column(Integer, default=0)
    pass_completion: Mapped[float] = mapped_column(Float, default=0.0)
    league_strength: Mapped[float] = mapped_column(Float, default=1.0)


class PlayerFeatures(Base):
    __tablename__ = "player_features"

    player_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("players.player_id"), primary_key=True
    )
    snapshot: Mapped[str] = mapped_column(String(32), primary_key=True)
    role_percentiles: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    style_vector: Mapped[list[float]] = mapped_column(VectorType(STYLE_VECTOR_DIM))
    ability_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class Price(Base):
    __tablename__ = "prices"

    player_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("players.player_id"), primary_key=True
    )
    tournament_snapshot: Mapped[str] = mapped_column(String(32), primary_key=True)
    price_eur: Mapped[int] = mapped_column(Integer)
    market_value_eur: Mapped[int] = mapped_column(Integer)
    ability_value_eur: Mapped[int] = mapped_column(Integer)


class TeamProfile(Base):
    __tablename__ = "team_profiles"

    team_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    snapshot: Mapped[str] = mapped_column(String(32), primary_key=True)
    attack_channels: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    ppda: Mapped[float] = mapped_column(Float)
    crosses_per_match: Mapped[float] = mapped_column(Float)
    set_piece_threat: Mapped[float] = mapped_column(Float)
    aerial: Mapped[float] = mapped_column(Float)
    danger_players: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)


class Document(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    doc_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(VectorType(EMBEDDING_DIM), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    embed_model: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GameSession(Base):
    __tablename__ = "game_sessions"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(16))
    opponent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC)
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    git_sha: Mapped[str] = mapped_column(String(40))
    metrics: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC)
    )
