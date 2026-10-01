"""Pydantic models that cross module boundaries inside engine/.

CLAUDE.md: "Pydantic models for all API schemas and for engine outputs that
cross module boundaries." Money is integer euros; ratings are floats 0-100,
rounded only at presentation (CLAUDE.md conventions).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlayerCard(BaseModel):
    """Everything the engine needs about one player. Built by pipeline/, read by engine/."""

    player_id: str
    name: str
    nationality: str
    position_group: str  # GK, DF, MF, FW
    position_code: str
    ability_score: float = Field(ge=0, le=100)
    price_eur: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1, default=1.0)
    role_fit: dict[str, float] = Field(default_factory=dict)
    per90: dict[str, float] = Field(default_factory=dict)
    preferred_foot: str = "right"
    natural_position_codes: list[str] = Field(default_factory=list)


class Lineup(BaseModel):
    """A formation plus whatever has been assigned to each of its slots so far."""

    formation: str
    assignments: dict[str, PlayerCard] = Field(default_factory=dict)  # slot_id -> player

    def player_ids(self) -> set[str]:
        return {p.player_id for p in self.assignments.values()}


class RuleViolation(BaseModel):
    code: str
    message: str
    slot_id: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    violations: list[RuleViolation] = Field(default_factory=list)
    budget_spent_eur: int = 0
    budget_left_eur: int = 0
    nationality_counts: dict[str, int] = Field(default_factory=dict)
    filled_slots: int = 0


class EligibilityResult(BaseModel):
    eligible: bool
    reason: str | None = None


class DangerPlayer(BaseModel):
    player_id: str
    name: str
    position_code: str
    ability_score: float
    note: str = ""


class TeamProfile(BaseModel):
    team_id: str
    name: str
    formation: str
    attack_channels: dict[str, float] = Field(default_factory=dict)
    ppda: float = 0.0
    crosses_per_match: float = 0.0
    set_piece_threat: float = 0.0
    aerial: float = 0.0
    danger_players: list[DangerPlayer] = Field(default_factory=list)


class SubRatings(BaseModel):
    attack: float
    midfield_control: float
    defence: float
    matchup: float
    cohesion: float
    balance: float


class RatingResult(BaseModel):
    sub_ratings: SubRatings
    overall: float = Field(ge=0, le=100)


class Weakness(BaseModel):
    type: str
    vertical_zone: str
    horizontal_zone: str
    severity: float = Field(ge=0, le=1)
    evidence: dict[str, float] = Field(default_factory=dict)
    affected_slots: list[str] = Field(default_factory=list)
    description: str = ""


class SwapSuggestion(BaseModel):
    weakness_type: str | None
    out_slot: str
    out_player_id: str
    out_player_name: str
    in_player: PlayerCard
    rating_before: float
    rating_after: float
    rating_gain: float
    price_delta_eur: int


class ManagerScoreResult(BaseModel):
    user_rating: float
    best_rating: float
    manager_score: float = Field(ge=0, le=1.5)


class CounterMove(BaseModel):
    move_type: str  # substitute | reposition | formation_change
    slot_id: str
    player_out_id: str | None = None
    player_out_name: str | None = None
    player_in_id: str | None = None
    player_in_name: str | None = None
    targeted_zone: str | None = None
    explanation: str = ""


class CounterRoundResult(BaseModel):
    round_number: int
    moves: list[CounterMove]
    rating_before: float
    rating_after: float
    opponent_formation: str


class MatchEvent(BaseModel):
    minute: int
    type: str  # goal | yellow_card | red_card | substitution
    side: str  # user | opponent
    player_name: str
    description: str = ""


class SimulationResult(BaseModel):
    win_pct: float
    draw_pct: float
    loss_pct: float
    score_distribution: dict[str, float]
    chance_share_by_zone: dict[str, float]
    narrative_events: list[MatchEvent] = Field(default_factory=list)
    narrative_score: tuple[int, int] = (0, 0)
    went_to_extra_time: bool = False
    went_to_penalties: bool = False
    penalty_score: tuple[int, int] | None = None


class LineupAnalysis(BaseModel):
    """Full coach report. Matches Phase 3 acceptance: documented in docs/PROGRESS.md."""

    session_id: str
    formation: str
    rating: RatingResult
    weaknesses: list[Weakness]
    swaps_by_weakness: dict[str, list[SwapSuggestion]]
    manager_score: ManagerScoreResult
    validation: ValidationResult
    win_draw_loss: tuple[float, float, float]
