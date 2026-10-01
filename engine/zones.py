"""Shared slot/zone helpers used by rating.py, matchups.py and weaknesses.py."""

from __future__ import annotations

import statistics

from config.game import Slot
from engine.rules import get_slots
from engine.schemas import Lineup


def slot_defs(formation: str) -> dict[str, Slot]:
    return {s.slot_id: s for s in get_slots(formation)}


def zone_average(
    lineup: Lineup, defs: dict[str, Slot], vertical: str, horizontal: str | None = None
) -> float | None:
    scores = [
        p.ability_score
        for slot_id, p in lineup.assignments.items()
        if slot_id in defs
        and defs[slot_id].vertical_zone == vertical
        and (horizontal is None or defs[slot_id].horizontal_zone == horizontal)
    ]
    return statistics.mean(scores) if scores else None
