"""Builds a guaranteed-11-player opponent XI from a real squad. docs/DECISIONS.md
"Thin squads": the opponent must always field exactly 11 players in a valid
formation -- when a position group is too thin, fill from the nearest adjacent
group (config.game.POSITION_GROUP_FALLBACK_CHAIN) rather than leaving a slot
empty. Returns None only when a squad is too thin to field 11 at all, even after
exhausting every fallback group -- graph/nodes.py's draw() excludes such squads.

docs/DECISIONS.md "Real opponent lineups from real match frequency" (Part 2c): an
optional `frequency` map (from pipeline.to_engine.load_lineup_frequency) ranks
candidates within a fallback tier by how many times they actually started at this
exact slot's position in a real recent match, falling back to role-fit only when
frequency is zero or tied -- "most frequent starters," not "most able players."
"""

from __future__ import annotations

from config.game import OPPONENT_FORMATION_SLOTS, POSITION_GROUP_FALLBACK_CHAIN
from engine.rating import role_fit_score
from engine.schemas import OpponentLineupResult, OutOfPositionFill, PlayerCard


def build_opponent_lineup(
    squad: list[PlayerCard], frequency: dict[tuple[str, str], int] | None = None
) -> OpponentLineupResult | None:
    by_group: dict[str, list[PlayerCard]] = {}
    for c in squad:
        by_group.setdefault(c.position_group, []).append(c)

    assignments: dict[str, str] = {}
    out_of_position: list[OutOfPositionFill] = []
    used: set[str] = set()
    real_fill_count = 0

    for slot_id, (native_group, position_code) in OPPONENT_FORMATION_SLOTS.items():
        picked: PlayerCard | None = None
        picked_via_frequency = False
        for group in POSITION_GROUP_FALLBACK_CHAIN[native_group]:
            candidates = [c for c in by_group.get(group, []) if c.player_id not in used]
            if not candidates:
                continue
            # Frequency first (real starts at this exact slot position), role-fit
            # as the tiebreak when frequency is zero/tied for everyone in this tier
            # -- the same out-of-position penalty engine/weaknesses.py already
            # applies to the user's own lineup, reused here as the fallback signal.
            candidates.sort(
                key=lambda c: (
                    (frequency or {}).get((c.player_id, position_code), 0),
                    role_fit_score(position_code, c),
                ),
                reverse=True,
            )
            picked = candidates[0]
            picked_via_frequency = bool((frequency or {}).get((picked.player_id, position_code), 0))
            break
        if picked is None:
            return None  # exhausted every fallback group -- this squad can't field 11

        assignments[slot_id] = picked.player_id
        used.add(picked.player_id)
        if picked_via_frequency:
            real_fill_count += 1
        if picked.position_group != native_group:
            out_of_position.append(
                OutOfPositionFill(
                    slot_id=slot_id,
                    player_id=picked.player_id,
                    player_name=picked.name,
                    natural_group=picked.position_group,
                    assigned_position_code=position_code,
                )
            )

    return OpponentLineupResult(
        assignments=assignments, out_of_position=out_of_position, real_fill_count=real_fill_count
    )
