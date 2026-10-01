"""Builds player_id_map by matching Understat records onto Transfermarkt identities.

Implements the Phase 1 prompt: "normalised name + date of birth + club; fuzzy match
only above a configurable threshold; write unresolved cases to a review CSV."
"""

from __future__ import annotations

import csv
import difflib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from pipeline.synthetic_source import TmPlayer, UnderstatPlayer

DEFAULT_FUZZY_THRESHOLD = 0.55


def normalize_name(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r"[^a-zA-Z\s]", " ", folded).lower()
    return re.sub(r"\s+", " ", folded).strip()


def _name_similarity(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    direct = difflib.SequenceMatcher(None, na, nb).ratio()
    sorted_a = " ".join(sorted(t for t in na.split() if len(t) > 1))
    sorted_b = " ".join(sorted(t for t in nb.split() if len(t) > 1))
    token_sorted = difflib.SequenceMatcher(None, sorted_a, sorted_b).ratio() if sorted_a and sorted_b else 0.0
    return max(direct, token_sorted)


@dataclass
class ResolvedMatch:
    player_id: str
    tm_id: str
    understat_id: str
    statsbomb_id: str | None
    match_method: str
    match_score: float


@dataclass
class UnresolvedCase:
    understat_id: str
    name: str
    dob: date
    club_name: str
    reason: str


def resolve(
    tm_players: list[TmPlayer],
    understat_players: list[UnderstatPlayer],
    clubs: list[dict[str, str]],
    *,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> tuple[list[ResolvedMatch], list[UnresolvedCase]]:
    club_name_by_id = {c["club_id"]: c["name"] for c in clubs}

    by_dob_club: dict[tuple[date, str], list[TmPlayer]] = {}
    by_dob: dict[date, list[TmPlayer]] = {}
    for p in tm_players:
        by_dob_club.setdefault((p.dob, club_name_by_id[p.club_id]), []).append(p)
        by_dob.setdefault(p.dob, []).append(p)

    matches: list[ResolvedMatch] = []
    unresolved: list[UnresolvedCase] = []
    claimed_tm_ids: set[str] = set()  # a real player's identity is matched at most once

    for u in understat_players:
        same_dob_club = [c for c in by_dob_club.get((u.dob, u.club_name), []) if c.tm_id not in claimed_tm_ids]

        if len(same_dob_club) == 1:
            candidate = same_dob_club[0]
            claimed_tm_ids.add(candidate.tm_id)
            matches.append(
                ResolvedMatch(candidate.tm_id, candidate.tm_id, u.understat_id, None, "dob_club_exact", 1.0)
            )
            continue

        if len(same_dob_club) > 1:
            scored = sorted(
                ((c, _name_similarity(u.name, c.name)) for c in same_dob_club),
                key=lambda t: t[1],
                reverse=True,
            )
            best, score = scored[0]
            if score >= fuzzy_threshold:
                claimed_tm_ids.add(best.tm_id)
                matches.append(
                    ResolvedMatch(best.tm_id, best.tm_id, u.understat_id, None, "dob_club_fuzzy", round(score, 3))
                )
                continue
            unresolved.append(
                UnresolvedCase(
                    u.understat_id, u.name, u.dob, u.club_name, "multiple dob+club matches, no name above threshold"
                )
            )
            continue

        same_dob = [c for c in by_dob.get(u.dob, []) if c.tm_id not in claimed_tm_ids]
        if same_dob:
            scored = sorted(
                ((c, _name_similarity(u.name, c.name)) for c in same_dob), key=lambda t: t[1], reverse=True
            )
            best, score = scored[0]
            if score >= fuzzy_threshold + 0.1:  # stricter: club didn't help narrow it down
                claimed_tm_ids.add(best.tm_id)
                matches.append(
                    ResolvedMatch(best.tm_id, best.tm_id, u.understat_id, None, "dob_only_fuzzy", round(score, 3))
                )
                continue

        unresolved.append(UnresolvedCase(u.understat_id, u.name, u.dob, u.club_name, "no dob match at all"))

    return matches, unresolved


def write_unresolved_csv(unresolved: list[UnresolvedCase], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["understat_id", "name", "dob", "club_name", "reason"])
        for u in unresolved:
            writer.writerow([u.understat_id, u.name, u.dob.isoformat(), u.club_name, u.reason])
