"""Swap optimizer. Implements docs/DESIGN.md section 7.5.

`candidate_pool` is expected to already be narrowed to a sane size (same position group,
roughly affordable, not in the opponent's squad) by whoever calls this — a DB query in
pipeline/ or api/, not this module. This module's job is the full-lineup re-scoring and
the hard guarantee that nothing it returns can ever break a rule (CLAUDE.md rule 3);
every candidate swap is round-tripped through rules.validate_lineup before it is offered.
"""

from __future__ import annotations

from config.game import SWAP_TOP_K
from engine.rating import RatingModel
from engine.rules import validate_lineup
from engine.schemas import Lineup, PlayerCard, SwapSuggestion, TeamProfile, Weakness
from engine.zones import slot_defs


def _target_slots_for_weakness(lineup: Lineup, weakness: Weakness) -> list[str]:
    if weakness.affected_slots:
        return [s for s in weakness.affected_slots if s in lineup.assignments]
    defs = slot_defs(lineup.formation)
    return [
        sid
        for sid, p in lineup.assignments.items()
        if sid in defs
        and defs[sid].vertical_zone == weakness.vertical_zone
        and defs[sid].horizontal_zone == weakness.horizontal_zone
    ]


def swaps_for_weakness(
    lineup: Lineup,
    opponent: TeamProfile,
    weakness: Weakness,
    candidate_pool: list[PlayerCard],
    opponent_squad_player_ids: set[str],
    rating_model: RatingModel,
    *,
    top_k: int = SWAP_TOP_K,
    max_candidates_per_slot: int = 40,
) -> list[SwapSuggestion]:
    target_slots = _target_slots_for_weakness(lineup, weakness)
    if not target_slots:
        return []

    base_rating = rating_model.rate(lineup, opponent).overall
    scored: list[SwapSuggestion] = []

    for slot_id in target_slots:
        outgoing = lineup.assignments[slot_id]
        defs = slot_defs(lineup.formation)
        slot = defs[slot_id]

        same_position = [
            c
            for c in candidate_pool
            if c.position_group == slot.position_group and c.player_id != outgoing.player_id
        ]
        same_position.sort(key=lambda c: c.ability_score, reverse=True)

        for candidate in same_position[:max_candidates_per_slot]:
            trial = Lineup(
                formation=lineup.formation,
                assignments={**lineup.assignments, slot_id: candidate},
            )
            validation = validate_lineup(
                trial, opponent_squad_player_ids, require_complete=False
            )
            if not validation.valid:
                continue  # never suggest a rule-breaking swap

            new_rating = rating_model.rate(trial, opponent).overall
            scored.append(
                SwapSuggestion(
                    weakness_type=weakness.type,
                    out_slot=slot_id,
                    out_player_id=outgoing.player_id,
                    out_player_name=outgoing.name,
                    in_player=candidate,
                    rating_before=round(base_rating, 1),
                    rating_after=round(new_rating, 1),
                    rating_gain=round(new_rating - base_rating, 1),
                    price_delta_eur=candidate.price_eur - outgoing.price_eur,
                )
            )

    scored.sort(key=lambda s: s.rating_gain, reverse=True)
    top = scored[: max(0, top_k - 1)]

    budget_freeing_candidates = [
        s
        for s in scored
        if s not in top and s.price_delta_eur < 0 and s.rating_gain >= -2.0
    ]
    budget_freeing_candidates.sort(key=lambda s: s.price_delta_eur)
    if budget_freeing_candidates and len(top) < top_k:
        top.append(budget_freeing_candidates[0])

    return top[:top_k]


def swaps_by_weakness(
    lineup: Lineup,
    opponent: TeamProfile,
    weaknesses: list[Weakness],
    candidate_pool: list[PlayerCard],
    opponent_squad_player_ids: set[str],
    rating_model: RatingModel,
) -> dict[str, list[SwapSuggestion]]:
    result: dict[str, list[SwapSuggestion]] = {}
    for weakness in weaknesses:
        key = f"{weakness.type}:{weakness.vertical_zone}:{weakness.horizontal_zone}"
        suggestions = swaps_for_weakness(
            lineup, opponent, weakness, candidate_pool, opponent_squad_player_ids, rating_model
        )
        if suggestions:
            result[key] = suggestions
    return result
