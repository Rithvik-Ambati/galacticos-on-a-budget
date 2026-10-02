"""API request/response Pydantic models. Implements docs/DESIGN.md section 11."""

from __future__ import annotations

from pydantic import BaseModel

from engine.schemas import EligibilityResult, LineupAnalysis, PlayerCard, SimulationResult


class ProblemDetails(BaseModel):
    """Consistent error schema (CLAUDE.md: "errors use a consistent problem-details schema")."""

    title: str
    detail: str
    status: int


class CreateSessionRequest(BaseModel):
    mode: str  # "wc" | "ucl"


class CreateSessionResponse(BaseModel):
    session_id: str
    mode: str


class DrawResponse(BaseModel):
    session_id: str
    opponent_team_id: str
    opponent_name: str
    awaiting: str


class ScoutingResponse(BaseModel):
    opponent_team_id: str
    attack_channels: dict[str, float]
    press_intensity_ppda: float
    crosses_per_match: float
    set_piece_threat: float
    aerial: float
    danger_players: list[dict[str, object]]


class PlayerSearchResult(BaseModel):
    player: PlayerCard
    eligibility: EligibilityResult


class PlayerSearchResponse(BaseModel):
    results: list[PlayerSearchResult]


class LineupSubmitRequest(BaseModel):
    formation: str
    assignments: dict[str, str]  # slot_id -> player_id


class LineupValidateResponse(BaseModel):
    valid: bool
    violations: list[str]
    budget_spent_eur: int
    budget_left_eur: int
    nationality_counts: dict[str, int]
    filled_slots: int


class AnalyseResponse(BaseModel):
    analysis: LineupAnalysis
    coach_report_text: str
    awaiting: str


class DecisionRequest(BaseModel):
    decision: str  # "counter" | "lock_in"


class DecisionResponse(BaseModel):
    awaiting: str
    counter_round: int | None = None
    last_counter_round: dict[str, object] | None = None
    analysis: LineupAnalysis | None = None
    coach_report_text: str | None = None
    simulation: SimulationResult | None = None
    match_report_text: str | None = None


class SimulateResponse(BaseModel):
    simulation: SimulationResult
    match_report_text: str


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str


class SessionStateResponse(BaseModel):
    session_id: str
    mode: str
    opponent_team_id: str | None
    formation: str | None
    lineup_assignments: dict[str, str]
    counter_round: int
    awaiting: str | None
    analysis: LineupAnalysis | None
    simulation: SimulationResult | None
    messages: list[dict[str, str]]
