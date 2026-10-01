"""Opponent best-response search. Implements docs/DESIGN.md section 7.7.

Deterministic given the same inputs (CLAUDE.md rule 4): there is no randomness here at
all, only exhaustive enumeration over a small move set with a stable sort, so the same
lineup + squad + seed always produces the same round.
"""

from __future__ import annotations

from config.game import (
    COUNTER_BEAM_WIDTH,
    COUNTER_MAX_CHANGES_PER_ROUND,
    COUNTER_MAX_ROUNDS,
    FORMATIONS,
)
from engine.rating import RatingModel, role_fit_score
from engine.schemas import CounterMove, CounterRoundResult, Lineup, PlayerCard, TeamProfile
from engine.zones import slot_defs


def _substitution_moves(opponent_lineup: Lineup, squad_pool: list[PlayerCard]) -> list[tuple[Lineup, CounterMove]]:
    fielded_ids = opponent_lineup.player_ids()
    bench = [p for p in squad_pool if p.player_id not in fielded_ids]
    out: list[tuple[Lineup, CounterMove]] = []

    for slot_id, starter in sorted(opponent_lineup.assignments.items()):
        for candidate in sorted(bench, key=lambda p: (-p.ability_score, p.player_id)):
            if candidate.position_group != starter.position_group:
                continue
            new_assignments = {**opponent_lineup.assignments, slot_id: candidate}
            trial = Lineup(formation=opponent_lineup.formation, assignments=new_assignments)
            move = CounterMove(
                move_type="substitute",
                slot_id=slot_id,
                player_out_id=starter.player_id,
                player_out_name=starter.name,
                player_in_id=candidate.player_id,
                player_in_name=candidate.name,
                targeted_zone=f"{slot_defs(opponent_lineup.formation)[slot_id].horizontal_zone}"
                f" {slot_defs(opponent_lineup.formation)[slot_id].vertical_zone}",
                explanation=f"{starter.name} off, {candidate.name} on at {slot_id}.",
            )
            out.append((trial, move))
    return out


def _reposition_moves(opponent_lineup: Lineup) -> list[tuple[Lineup, CounterMove]]:
    defs = slot_defs(opponent_lineup.formation)
    out: list[tuple[Lineup, CounterMove]] = []
    slot_ids = sorted(opponent_lineup.assignments)

    for i, slot_a in enumerate(slot_ids):
        for slot_b in slot_ids[i + 1 :]:
            if defs[slot_a].position_group != defs[slot_b].position_group:
                continue
            if defs[slot_a].horizontal_zone == defs[slot_b].horizontal_zone:
                continue  # swapping identical zones changes nothing
            player_a = opponent_lineup.assignments[slot_a]
            player_b = opponent_lineup.assignments[slot_b]
            new_assignments = {**opponent_lineup.assignments, slot_a: player_b, slot_b: player_a}
            trial = Lineup(formation=opponent_lineup.formation, assignments=new_assignments)
            move = CounterMove(
                move_type="reposition",
                slot_id=f"{slot_a}<->{slot_b}",
                player_out_id=player_a.player_id,
                player_out_name=player_a.name,
                player_in_id=player_b.player_id,
                player_in_name=player_b.name,
                targeted_zone=f"{defs[slot_a].horizontal_zone}/{defs[slot_b].horizontal_zone}",
                explanation=f"{player_a.name} and {player_b.name} swap sides.",
            )
            out.append((trial, move))
    return out


def _greedy_lineup_for_formation(formation: str, squad_pool: list[PlayerCard]) -> Lineup:
    """Fast heuristic re-assignment of an existing squad to a new formation's slots.

    Not a global optimum (engine/optimizer.py's ILP is, for the user's own budgeted XI) —
    this only needs to be a plausible, fast re-shuffle of a squad the opponent already
    owns, with no budget or nationality constraint, so greedy-by-role-fit is enough and
    keeps formation-change moves well under the Phase 4 1-second budget.
    """
    slots = sorted(FORMATIONS[formation], key=lambda s: s.slot_id)
    remaining = list(squad_pool)
    assignments: dict[str, PlayerCard] = {}
    for slot in slots:
        pool = [p for p in remaining if p.position_group == slot.position_group]
        if not pool:
            continue
        best = max(pool, key=lambda p: role_fit_score(slot.position_code, p))
        assignments[slot.slot_id] = best
        remaining.remove(best)
    return Lineup(formation=formation, assignments=assignments)


def _formation_change_moves(
    opponent_lineup: Lineup, squad_pool: list[PlayerCard]
) -> list[tuple[Lineup, CounterMove]]:
    fielded = list(opponent_lineup.assignments.values())
    full_pool = fielded + [p for p in squad_pool if p.player_id not in opponent_lineup.player_ids()]
    out: list[tuple[Lineup, CounterMove]] = []

    for formation in sorted(FORMATIONS):
        if formation == opponent_lineup.formation:
            continue
        trial = _greedy_lineup_for_formation(formation, full_pool)
        if len(trial.assignments) < len(FORMATIONS[formation]):
            continue  # not enough eligible players to fill this formation, skip it
        move = CounterMove(
            move_type="formation_change",
            slot_id="formation",
            targeted_zone=None,
            explanation=f"Switches from {opponent_lineup.formation} to {formation}.",
        )
        out.append((trial, move))
    return out


def run_counter_round(
    round_number: int,
    user_lineup: Lineup,
    opponent_lineup: Lineup,
    opponent_profile: TeamProfile,
    opponent_squad_pool: list[PlayerCard],
    rating_model: RatingModel,
) -> tuple[CounterRoundResult, Lineup]:
    """One round of the opponent's best response. Returns the round result plus the
    opponent's new lineup (callers run up to COUNTER_MAX_ROUNDS rounds)."""
    if round_number > COUNTER_MAX_ROUNDS:
        raise ValueError(f"Round {round_number} exceeds the {COUNTER_MAX_ROUNDS}-round cap")

    rating_before = rating_model.rate(user_lineup, opponent_profile, opponent_lineup).overall

    single_moves = (
        _substitution_moves(opponent_lineup, opponent_squad_pool)
        + _reposition_moves(opponent_lineup)
        + _formation_change_moves(opponent_lineup, opponent_squad_pool)
    )

    def score(lineup: Lineup) -> float:
        return rating_model.rate(user_lineup, opponent_profile, lineup).overall

    scored_single = sorted(
        ((score(lineup), lineup, [move]) for lineup, move in single_moves),
        key=lambda t: (t[0], t[1].formation, tuple(sorted(t[1].assignments))),
    )
    beam = scored_single[:COUNTER_BEAM_WIDTH]

    best_rating, best_lineup, best_moves = beam[0] if beam else (
        rating_before,
        opponent_lineup,
        [],
    )

    if COUNTER_MAX_CHANGES_PER_ROUND >= 2:
        for _base_rating, base_lineup, base_moves in beam:
            second_round_moves = _substitution_moves(base_lineup, opponent_squad_pool) + _reposition_moves(
                base_lineup
            )
            for lineup2, move2 in second_round_moves:
                rating2 = score(lineup2)
                if rating2 < best_rating:
                    best_rating, best_lineup, best_moves = rating2, lineup2, [*base_moves, move2]

    result = CounterRoundResult(
        round_number=round_number,
        moves=best_moves,
        rating_before=round(rating_before, 1),
        rating_after=round(best_rating, 1),
        opponent_formation=best_lineup.formation,
    )
    return result, best_lineup
