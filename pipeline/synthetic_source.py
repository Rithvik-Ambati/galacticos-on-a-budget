"""Synthetic stand-in for the real Transfermarkt Datasets (dcaribou) and Understat
pulls. docs/DECISIONS.md explains why: there was no time/network budget in this build
to actually scrape or bulk-download either source, and CLAUDE.md rule "stop and ask
rather than guess" means that gap gets documented loudly, not hidden.

The two tables this module emits are deliberately shaped like two independent, messy
real sources that disagree about names and never ID-match directly — exactly the
problem pipeline/id_resolution.py exists to solve — rather than one clean table that
makes id_resolution a no-op.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from config.settings import get_settings

FIRST_NAMES = [
    "Luca", "Marco", "Diego", "Mateo", "Noah", "Leo", "Hugo", "Elias", "Theo", "Enzo",
    "Rafael", "Gabriel", "Samuel", "Daniel", "Lucas", "Mikel", "Iker", "Pau", "Jules",
    "Kylian", "Antoine", "Ousmane", "Aurelien", "Wesley", "Bruno", "Joao", "Pedro",
    "Thiago", "Vinicius", "Rodrigo", "Andres", "Carlos", "Sergio", "Alvaro", "Martin",
    "Erling", "Jude", "Phil", "Marcus", "Bukayo", "Declan", "Kobbie", "Florian",
    "Jamal", "Leon", "Kai", "Niklas", "Joshua", "Serge", "Youssouf",
]
LAST_NAMES = [
    "Silva", "Santos", "Oliveira", "Pereira", "Fernandez", "Gonzalez", "Rodriguez",
    "Martinez", "Lopez", "Garcia", "Moreau", "Bernard", "Lefevre", "Rossi", "Bianchi",
    "Ferrari", "Muller", "Schmidt", "Weber", "Fischer", "Johansson", "Andersen",
    "Kowalski", "Nowak", "Van Dijk", "De Jong", "Yilmaz", "Demir", "Costa", "Araujo",
    "Ramos", "Torres", "Hernandez", "Dubois", "Petit", "Keita", "Toure", "Diallo",
    "Camara", "Traore",
]

# 12 countries with WC2026 squads, deep enough in the player pool to field 23 each.
WC_COUNTRIES = ["BRA", "ARG", "FRA", "ESP", "ENG", "GER", "POR", "NED", "ITA", "URU", "MAR", "JPN"]
# A broader nationality pool so club squads (UCL) aren't just the 12 WC countries.
EXTRA_COUNTRIES = ["BEL", "CRO", "SRB", "COL", "SEN", "GHA", "USA", "MEX", "DEN", "SUI", "AUT", "TUR"]
ALL_COUNTRIES = WC_COUNTRIES + EXTRA_COUNTRIES

CLUB_NAMES = [
    ("Real Blanco", "ESP"), ("Catalonia FC", "ESP"), ("Northside United", "ENG"),
    ("Merseyside Rovers", "ENG"), ("Bavaria Munich", "GER"), ("Ruhr Dortmund", "GER"),
    ("Lombardy Milan", "ITA"), ("Piedmont Turin", "ITA"), ("Seine Paris", "FRA"),
    ("Rhone Lyon", "FRA"),
]

POSITIONS = {
    "GK": ["GK"],
    "DF": ["LB", "CB", "RB"],
    "MF": ["DM", "CM", "AM"],
    "FW": ["LW", "ST", "RW"],
}
GROUP_WEIGHTS = {"GK": 3, "DF": 9, "MF": 8, "FW": 6}  # ~26-man-squad-shaped distribution


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


@dataclass
class TmPlayer:
    tm_id: str
    name: str
    dob: date
    nationality: str
    position_group: str
    position_code: str
    preferred_foot: str
    height_cm: int
    club_id: str
    true_quality: float  # 0-100 latent skill, drives both stats and market value
    market_value_eur: int


@dataclass
class UnderstatPlayer:
    understat_id: str
    name: str  # deliberately perturbed vs. the TM name
    dob: date
    club_name: str
    minutes: int
    goals: int
    assists: int
    xg: float
    xa: float
    shots: int
    key_passes: int
    tackles_won: int
    dribbled_past: int
    aerials_won: int
    aerials_total: int
    progressive_carries: int
    take_ons_won: int
    pass_completion: float
    tm_id_for_grading_only: str = field(repr=False, default="")  # never used by id_resolution


@dataclass
class SyntheticWorld:
    clubs: list[dict[str, str]]
    national_teams: list[dict[str, str]]
    tm_players: list[TmPlayer]
    understat_players: list[UnderstatPlayer]
    wc_squads: dict[str, list[str]]  # team_id -> [tm_id, ...]
    ucl_squads: dict[str, list[str]]  # club_id -> [tm_id, ...]
    # Part 2c (docs/DECISIONS.md "Real opponent lineups from real match frequency"):
    # team_id -> {(tm_id, position_code): times started at that position in a real
    # recent match}. None for synthetic data, which has no real match history --
    # engine/opponent_lineup.py falls back to its ability-only builder either way.
    lineup_frequency: dict[str, dict[tuple[str, str], int]] | None = None


def _perturbed_name(rng: random.Random, name: str) -> str:
    """Understat-style name drift: folded accents, nickname shortening, or reordering —
    enough disagreement that exact-string matching fails and id_resolution has to work."""
    folded = _strip_accents(name)
    parts = folded.split()
    choice = rng.random()
    if choice < 0.35 and len(parts) > 1:
        return f"{parts[-1]}, {parts[0][0]}."
    if choice < 0.6 and len(parts) > 1:
        return " ".join(parts[:1] + [p[0] + "." for p in parts[1:-1]] + [parts[-1]])
    return folded


def generate(seed: int | None = None) -> SyntheticWorld:
    rng = random.Random(seed if seed is not None else get_settings().seed)

    clubs = [
        {"club_id": f"club_{i}", "name": name, "country": country, "competition": "UCL2026"}
        for i, (name, country) in enumerate(CLUB_NAMES)
    ]

    national_teams = [
        {"team_id": f"nt_{country}", "name": country, "country": country, "competition": "WC2026"}
        for country in WC_COUNTRIES
    ]

    tm_players: list[TmPlayer] = []
    player_counter = 0

    def make_player(nationality: str, club_id: str) -> TmPlayer:
        nonlocal player_counter
        player_counter += 1
        group = rng.choices(list(GROUP_WEIGHTS), weights=list(GROUP_WEIGHTS.values()))[0]
        code = rng.choice(POSITIONS[group])
        quality = max(30.0, min(99.0, rng.gauss(68, 13)))
        age = rng.randint(17, 37)
        birth_year = date.today().year - age
        dob = date(birth_year, rng.randint(1, 12), rng.randint(1, 28))
        # Tuned so a full top-ability XI does NOT fit under the EUR500M budget alongside
        # a realistic squad -- docs/PROGRESS.md Phase 2 records the original curve that
        # failed that budget sanity check and why this one replaced it, per the Phase 2
        # prompt's "report it and propose a curve adjustment rather than silently
        # changing it" instruction.
        market_value = int(max(1, (quality / 45) ** 6.0) * 1_500_000 * rng.uniform(0.7, 1.3))
        return TmPlayer(
            tm_id=f"p_{player_counter}",
            name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            dob=dob,
            nationality=nationality,
            position_group=group,
            position_code=code,
            preferred_foot=rng.choices(["right", "left"], weights=[75, 25])[0],
            height_cm=rng.randint(168, 198),
            club_id=club_id,
            true_quality=round(quality, 1),
            market_value_eur=market_value,
        )

    # Enough depth per WC country to field a 23-man squad from nationality alone.
    for country in WC_COUNTRIES:
        for _ in range(30):
            tm_players.append(make_player(country, rng.choice(clubs)["club_id"]))

    # Club-squad depth: ~25 players per club, nationality drawn from the full pool
    # (this is what actually fills out UCL squads, not the WC blocks above).
    for club in clubs:
        for _ in range(25):
            tm_players.append(make_player(rng.choice(ALL_COUNTRIES), club["club_id"]))

    # A general-purpose free-agent-ish pool: eligible for the user's XI, in nobody's
    # declared squad, spanning every nationality (keeps the candidate pool wide).
    for _ in range(220):
        tm_players.append(make_player(rng.choice(ALL_COUNTRIES), rng.choice(clubs)["club_id"]))

    wc_squads: dict[str, list[str]] = {}
    for country in WC_COUNTRIES:
        pool = [p for p in tm_players if p.nationality == country]
        rng.shuffle(pool)
        wc_squads[f"nt_{country}"] = [p.tm_id for p in pool[:23]]

    ucl_squads: dict[str, list[str]] = {}
    for club in clubs:
        pool = [p for p in tm_players if p.club_id == club["club_id"]]
        ucl_squads[club["club_id"]] = [p.tm_id for p in pool[:25]]

    club_by_id = {c["club_id"]: c for c in clubs}
    understat_players: list[UnderstatPlayer] = []
    for p in tm_players:
        club = club_by_id[p.club_id]
        in_top_league = club["country"] in {"ESP", "ENG", "GER", "ITA", "FRA"}
        if not (in_top_league and rng.random() < 0.85):
            continue  # Understat's real-world coverage gap -> low-confidence flag later

        minutes = rng.randint(400, 3200)
        per90 = minutes / 90.0
        # Every metric's mean scales with quality/50 (50 -> 1.0x, 90 -> 1.8x, 30 -> 0.6x),
        # so ability scoring in pipeline/features.py has real signal to rank on, the way
        # a real per-90 stat would actually track with a player's underlying level.
        q = p.true_quality / 50.0
        attack_bias = 1.6 if p.position_group == "FW" else (1.0 if p.position_group == "MF" else 0.25)
        defence_bias = 1.6 if p.position_group == "DF" else (1.0 if p.position_group == "MF" else 0.3)

        xg = round(max(0.0, rng.gauss(0.35 * q * attack_bias, 0.08)) * per90, 2)
        xa = round(max(0.0, rng.gauss(0.22 * q * attack_bias, 0.06)) * per90, 2)
        # a fixed, quality-independent contest count -- so the WIN ratio below (not just
        # the raw won-count) is what actually tracks quality, the way a real stat would.
        aerial_contests = max(1, rng.gauss(2.2, 0.6)) * per90
        aerial_win_rate = max(0.1, min(0.95, 0.35 + 0.18 * q))

        understat_players.append(
            UnderstatPlayer(
                understat_id=f"u_{p.tm_id}",
                name=_perturbed_name(rng, p.name),
                dob=p.dob,
                club_name=club["name"],
                minutes=minutes,
                goals=int(xg * rng.uniform(0.75, 1.25)),
                assists=int(xa * rng.uniform(0.75, 1.25)),
                xg=xg,
                xa=xa,
                shots=int(max(0, rng.gauss(2.2 * q * attack_bias, 0.6)) * per90),
                key_passes=int(max(0, rng.gauss(1.0 * q, 0.5)) * per90),
                tackles_won=int(max(0, rng.gauss(1.4 * q * defence_bias, 0.5)) * per90),
                dribbled_past=int(max(0, rng.gauss(2.0 / q, 0.5)) * per90),  # inverse: weaker -> more
                aerials_won=int(aerial_contests * aerial_win_rate),
                aerials_total=int(aerial_contests),
                progressive_carries=int(max(0, rng.gauss(1.6 * q, 0.6)) * per90),
                take_ons_won=int(max(0, rng.gauss(0.8 * q * attack_bias, 0.4)) * per90),
                pass_completion=round(min(98.0, max(55.0, rng.gauss(55 + 0.35 * p.true_quality, 3))), 1),
                tm_id_for_grading_only=p.tm_id,
            )
        )

    return SyntheticWorld(
        clubs=clubs,
        national_teams=national_teams,
        tm_players=tm_players,
        understat_players=understat_players,
        wc_squads=wc_squads,
        ucl_squads=ucl_squads,
    )
