"""Hand-built demo data: the same Brazil scenario from the Lineup Lab mockup.

Used by `python -m engine.analyse --demo`, and by tests so "does the engine find the
weakness I planted" has one shared, readable source of truth instead of being
re-invented per test file.
"""

from __future__ import annotations

from typing import Any

from engine.schemas import DangerPlayer, Lineup, PlayerCard, TeamProfile

BRAZIL_PROFILE = TeamProfile(
    team_id="bra",
    name="Brazil",
    formation="4-2-3-1",
    attack_channels={"left": 24.0, "center": 32.0, "right": 62.0},
    ppda=7.5,  # aggressive press
    crosses_per_match=14.2,
    set_piece_threat=71.0,
    aerial=54.0,
    danger_players=[
        DangerPlayer(
            player_id="bra_9", name="V. Rodrigues", position_code="ST", ability_score=94,
            note="Elite movement in the box; wins most aerials vs a shorter CB.",
        ),
        DangerPlayer(
            player_id="bra_11", name="E. Martins", position_code="RW", ability_score=91,
            note="Isolates full-backs 1v1; needs real recovery pace against him.",
        ),
        DangerPlayer(
            player_id="bra_8", name="R. Azevedo", position_code="CM", ability_score=87,
            note="Dictates tempo; press him early or he finds the right winger every time.",
        ),
    ],
)


def _p(
    player_id: str, name: str, nat: str, group: str, code: str, ability: float, price_m: float, **kw: Any
) -> PlayerCard:
    return PlayerCard(
        player_id=player_id,
        name=name,
        nationality=nat,
        position_group=group,
        position_code=code,
        ability_score=ability,
        price_eur=int(price_m * 1_000_000),
        **kw,
    )


BRAZIL_SQUAD: list[PlayerCard] = [
    _p("bra_1", "A. Weverton", "BRA", "GK", "GK", 80, 18),
    _p("bra_2", "D. Alencar", "BRA", "DF", "RB", 83, 30),
    _p("bra_3", "M. Silva", "BRA", "DF", "CB", 85, 42),
    _p("bra_4", "G. Magalhaes", "BRA", "DF", "CB", 84, 38),
    _p("bra_6", "J. Clauss_BR", "BRA", "DF", "LB", 82, 29),
    _p("bra_5", "Casemiro_BR", "BRA", "MF", "DM", 86, 45),
    _p("bra_8", "R. Azevedo", "BRA", "MF", "CM", 87, 48, role_fit={"ball_winning_dm": 70, "box_to_box": 85}),
    _p("bra_10", "Neymar_BR", "BRA", "MF", "AM", 89, 55),
    _p("bra_7", "Raphinha_BR", "BRA", "FW", "LW", 86, 40),
    _p("bra_11", "E. Martins", "BRA", "FW", "RW", 91, 58, per90={"aerial_win_pct": 50}),
    _p("bra_9", "V. Rodrigues", "BRA", "FW", "ST", 94, 70, per90={"aerial_win_pct": 68}),
    # bench
    _p("bra_12", "Ederson_BR", "BRA", "GK", "GK", 84, 32),
    _p("bra_13", "Danilo_BR", "BRA", "DF", "RB", 78, 20),
    _p("bra_14", "Militao_BR", "BRA", "DF", "CB", 81, 26),
    _p("bra_15", "Fabinho_BR", "BRA", "MF", "DM", 80, 22),
    _p("bra_16", "Rodrygo_BR", "BRA", "FW", "RW", 85, 38),
    _p("bra_17", "Endrick_BR", "BRA", "FW", "ST", 82, 24),
]

BRAZIL_OPPONENT_LINEUP = Lineup(
    formation="4-2-3-1",
    assignments={
        "GK": BRAZIL_SQUAD[0],
        "RB": BRAZIL_SQUAD[1],
        "CB1": BRAZIL_SQUAD[2],
        "CB2": BRAZIL_SQUAD[3],
        "LB": BRAZIL_SQUAD[4],
        "DM1": BRAZIL_SQUAD[5],
        "DM2": BRAZIL_SQUAD[6],
        "LAM": BRAZIL_SQUAD[8],
        "CAM": BRAZIL_SQUAD[7],
        "RAM": BRAZIL_SQUAD[9],
        "ST": BRAZIL_SQUAD[10],
    },
)

BRAZIL_SQUAD_IDS: set[str] = {p.player_id for p in BRAZIL_SQUAD}

# A non-Brazil candidate pool big enough for real swap/optimizer/nationality-limit tests.
CANDIDATE_POOL: list[PlayerCard] = [
    _p("gk_moreno", "A. Moreno", "ESP", "GK", "GK", 82, 22),
    _p("lb_hernandez", "T. Hernandez", "FRA", "DF", "LB", 86, 41, preferred_foot="left",
       per90={"aerial_win_pct": 55, "duel_strength": 74}),
    _p("lb_robertson", "A. Robertson", "SCO", "DF", "LB", 89, 52, preferred_foot="left",
       per90={"aerial_win_pct": 50, "duel_strength": 90}),
    _p("lb_mendy", "N. Mendy", "FRA", "DF", "LB", 88, 39, preferred_foot="left"),
    _p("lb_tsimikas", "Y. Tsimikas", "GRE", "DF", "LB", 85, 28, preferred_foot="left"),
    _p("cb_araujo", "R. Araujo", "URU", "DF", "CB", 88, 46, per90={"aerial_win_pct": 66}),
    _p("cb_saliba", "W. Saliba", "FRA", "DF", "CB", 87, 44, per90={"aerial_win_pct": 70}),
    _p("rb_hakimi", "A. Hakimi", "MAR", "DF", "RB", 90, 44, preferred_foot="right",
       per90={"aerial_win_pct": 48}),
    _p("rb_walker", "T. Walker", "ENG", "DF", "RB", 84, 33, preferred_foot="right"),
    _p("dm_rodri", "Rodri", "ESP", "MF", "DM", 93, 68, role_fit={"ball_winning_dm": 92, "deep_lying_playmaker": 88},
       per90={"press_resistance": 88}),
    _p("cm_pedri", "Pedri", "ESP", "MF", "CM", 89, 61, role_fit={"box_to_box": 80},
       per90={"press_resistance": 74}),
    _p("cm_bellingham", "J. Bellingham", "ENG", "MF", "CM", 91, 61, role_fit={"box_to_box": 93},
       per90={"press_resistance": 85}),
    # Brazilian but NOT in Brazil's declared squad above -> eligible per docs/DESIGN.md
    # section 1's decided edge case, still counted against the BRA nationality limit.
    _p("lw_vinicius", "Vinicius Jr", "BRA", "FW", "LW", 94, 79),
    _p("rw_rashford", "M. Rashford", "ENG", "FW", "RW", 85, 35),
    _p("st_mbappe", "K. Mbappe", "FRA", "FW", "ST", 96, 92, role_fit={"poacher": 90}),
    _p("st_haaland", "E. Haaland", "NOR", "FW", "ST", 95, 88, role_fit={"poacher": 97},
       per90={"aerial_win_pct": 62}),
    # filler depth so the optimizer/swap search has more than exactly one choice per slot
    _p("gk_filler", "M. Neuer_jr", "GER", "GK", "GK", 75, 14),
    _p("cb_filler", "C. Romero", "ARG", "DF", "CB", 83, 32, per90={"aerial_win_pct": 58}),
    _p("rb_filler", "D. Carvajal", "ESP", "DF", "RB", 81, 24),
    _p("cm_filler", "B. Fernandes", "POR", "MF", "CM", 84, 36, per90={"press_resistance": 76}),
    _p("rw_filler", "B. Saka", "ENG", "FW", "RW", 87, 42),
]


def build_demo_lineup(scenario: str) -> Lineup:
    """One of "strong", "weak_leftback", "all_attack" — the three hand-built lineups the
    Phase 3 prompt's manual check asks for, all in 4-3-3 against BRAZIL_PROFILE."""
    by_id = {p.player_id: p for p in CANDIDATE_POOL}

    if scenario == "strong":
        codes = {
            "GK": "gk_moreno", "LB": "lb_robertson", "CB1": "cb_araujo", "CB2": "cb_saliba",
            "RB": "rb_hakimi", "DM": "dm_rodri", "LCM": "cm_bellingham", "RCM": "cm_pedri",
            "LW": "lw_vinicius", "ST": "st_mbappe", "RW": "rw_rashford",
        }
    elif scenario == "weak_leftback":
        codes = {
            "GK": "gk_moreno", "LB": "lb_hernandez", "CB1": "cb_araujo", "CB2": "cb_saliba",
            "RB": "rb_hakimi", "DM": "dm_rodri", "LCM": "cm_bellingham", "RCM": "cm_pedri",
            "LW": "lw_vinicius", "ST": "st_mbappe", "RW": "rw_rashford",
        }
    elif scenario == "all_attack":
        codes = {
            "GK": "gk_moreno", "LB": "lb_tsimikas", "CB1": "cb_araujo", "CB2": "cb_saliba",
            "RB": "rb_walker", "DM": "cm_pedri", "LCM": "cm_bellingham", "RCM": "cm_filler",
            "LW": "lw_vinicius", "ST": "st_mbappe", "RW": "rw_filler",
        }
    else:
        raise ValueError(f"Unknown demo scenario {scenario!r}")

    return Lineup(formation="4-3-3", assignments={slot: by_id[pid] for slot, pid in codes.items()})
