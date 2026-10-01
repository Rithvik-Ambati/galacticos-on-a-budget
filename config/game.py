"""Game constants, formation templates, rating weights and thresholds.

Implements docs/DESIGN.md section 1 (game rules) and section 7 (models).
CLAUDE.md rule: no magic numbers in engine logic — everything tunable lives here.
"""

from __future__ import annotations

from dataclasses import dataclass

BUDGET_EUR: int = 500_000_000
NATIONALITY_LIMIT: int = 3
SQUAD_SIZE: int = 11

PRICE_FLOOR_EUR: int = 1_000_000
PRICE_ROUND_EUR: int = 1_000_000
PRICING_ABILITY_WEIGHT: float = 0.7
PRICING_MARKET_WEIGHT: float = 0.3


@dataclass(frozen=True)
class Slot:
    slot_id: str
    position_group: str  # GK, DF, MF, FW
    position_code: str  # LB, CB, RB, DM, CM, LW, ST, RW, ...
    vertical_zone: str  # def, mid, att
    horizontal_zone: str  # left, center, right


FORMATIONS: dict[str, tuple[Slot, ...]] = {
    "4-3-3": (
        Slot("GK", "GK", "GK", "def", "center"),
        Slot("LB", "DF", "LB", "def", "left"),
        Slot("CB1", "DF", "CB", "def", "center"),
        Slot("CB2", "DF", "CB", "def", "center"),
        Slot("RB", "DF", "RB", "def", "right"),
        Slot("DM", "MF", "DM", "mid", "center"),
        Slot("LCM", "MF", "CM", "mid", "left"),
        Slot("RCM", "MF", "CM", "mid", "right"),
        Slot("LW", "FW", "LW", "att", "left"),
        Slot("ST", "FW", "ST", "att", "center"),
        Slot("RW", "FW", "RW", "att", "right"),
    ),
    "4-4-2": (
        Slot("GK", "GK", "GK", "def", "center"),
        Slot("LB", "DF", "LB", "def", "left"),
        Slot("CB1", "DF", "CB", "def", "center"),
        Slot("CB2", "DF", "CB", "def", "center"),
        Slot("RB", "DF", "RB", "def", "right"),
        Slot("LM", "MF", "LM", "mid", "left"),
        Slot("CM1", "MF", "CM", "mid", "center"),
        Slot("CM2", "MF", "CM", "mid", "center"),
        Slot("RM", "MF", "RM", "mid", "right"),
        Slot("ST1", "FW", "ST", "att", "center"),
        Slot("ST2", "FW", "ST", "att", "center"),
    ),
    "4-2-3-1": (
        Slot("GK", "GK", "GK", "def", "center"),
        Slot("LB", "DF", "LB", "def", "left"),
        Slot("CB1", "DF", "CB", "def", "center"),
        Slot("CB2", "DF", "CB", "def", "center"),
        Slot("RB", "DF", "RB", "def", "right"),
        Slot("DM1", "MF", "DM", "mid", "left"),
        Slot("DM2", "MF", "DM", "mid", "right"),
        Slot("LAM", "MF", "AM", "att", "left"),
        Slot("CAM", "MF", "AM", "att", "center"),
        Slot("RAM", "MF", "AM", "att", "right"),
        Slot("ST", "FW", "ST", "att", "center"),
    ),
    "3-5-2": (
        Slot("GK", "GK", "GK", "def", "center"),
        Slot("CB1", "DF", "CB", "def", "left"),
        Slot("CB2", "DF", "CB", "def", "center"),
        Slot("CB3", "DF", "CB", "def", "right"),
        Slot("LM", "MF", "LWB", "mid", "left"),
        Slot("CM1", "MF", "CM", "mid", "center"),
        Slot("CM2", "MF", "CM", "mid", "center"),
        Slot("CM3", "MF", "CM", "mid", "center"),
        Slot("RM", "MF", "RWB", "mid", "right"),
        Slot("ST1", "FW", "ST", "att", "center"),
        Slot("ST2", "FW", "ST", "att", "center"),
    ),
    "3-4-3": (
        Slot("GK", "GK", "GK", "def", "center"),
        Slot("CB1", "DF", "CB", "def", "left"),
        Slot("CB2", "DF", "CB", "def", "center"),
        Slot("CB3", "DF", "CB", "def", "right"),
        Slot("LM", "MF", "LM", "mid", "left"),
        Slot("CM1", "MF", "CM", "mid", "center"),
        Slot("CM2", "MF", "CM", "mid", "center"),
        Slot("RM", "MF", "RM", "mid", "right"),
        Slot("LW", "FW", "LW", "att", "left"),
        Slot("ST", "FW", "ST", "att", "center"),
        Slot("RW", "FW", "RW", "att", "right"),
    ),
    "5-3-2": (
        Slot("GK", "GK", "GK", "def", "center"),
        Slot("LB", "DF", "LB", "def", "left"),
        Slot("CB1", "DF", "CB", "def", "center"),
        Slot("CB2", "DF", "CB", "def", "center"),
        Slot("CB3", "DF", "CB", "def", "center"),
        Slot("RB", "DF", "RB", "def", "right"),
        Slot("CM1", "MF", "CM", "mid", "left"),
        Slot("CM2", "MF", "CM", "mid", "center"),
        Slot("CM3", "MF", "CM", "mid", "right"),
        Slot("ST1", "FW", "ST", "att", "center"),
        Slot("ST2", "FW", "ST", "att", "center"),
    ),
}

ROLE_TEMPLATES: tuple[str, ...] = (
    "ball_playing_cb",
    "stopper_cb",
    "inverted_fb",
    "overlapping_fb",
    "ball_winning_dm",
    "deep_lying_playmaker",
    "box_to_box",
    "inside_forward",
    "winger",
    "poacher",
    "target_man",
)

# Rating v1 sub-rating weights; must sum to 1.0 (tests enforce this).
RATING_WEIGHTS: dict[str, float] = {
    "attack": 0.22,
    "midfield_control": 0.18,
    "defence": 0.22,
    "matchup": 0.20,
    "cohesion": 0.10,
    "balance": 0.08,
}

WEAKNESS_THRESHOLDS: dict[str, float] = {
    "zone_mismatch": 12.0,  # opponent-threat minus defender-strength, 0-100 scale
    "press_resistance": 80.0,  # minimum for a pivot role vs a high press
    "aerial_risk": 65.0,  # opponent set-piece/cross threat above this needs aerial cover
    "set_piece_threat": 65.0,
    "low_confidence": 0.5,  # player confidence flag below this is "low coverage"
}

SWAP_TOP_K: int = 3

COUNTER_BEAM_WIDTH: int = 5
COUNTER_MAX_CHANGES_PER_ROUND: int = 2
COUNTER_MAX_ROUNDS: int = 3

SIMULATION_RUNS: int = 10_000
EXTRA_TIME_FRACTION: float = 30.0 / 90.0
EXTRA_TIME_STAMINA_FACTOR: float = 0.9
PENALTY_LEAGUE_AVERAGE_CONVERSION: float = 0.76
HOME_ADVANTAGE_LAMBDA_MULTIPLIER: float = 1.08
AWAY_DISADVANTAGE_LAMBDA_MULTIPLIER: float = 0.95
