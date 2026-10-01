"""Optimal-lineup ILP solver and manager score. Implements docs/DESIGN.md section 7.6."""

from __future__ import annotations

from ortools.sat.python import cp_model

from config.game import BUDGET_EUR, NATIONALITY_LIMIT
from engine.rating import RatingModel, role_fit_score
from engine.rules import get_slots
from engine.schemas import Lineup, ManagerScoreResult, PlayerCard, TeamProfile


def find_optimal_lineup(
    formation: str,
    candidate_pool: list[PlayerCard],
    opponent_squad_player_ids: set[str],
    *,
    time_limit_seconds: float = 5.0,
) -> Lineup | None:
    """Best lineup under budget + nationality constraints, maximising role fit.

    Returns None if no feasible lineup exists within the pool (e.g. too few players at
    some position to fill every slot) — callers should treat that as "can't solve",
    never guess a partial lineup.
    """
    slots = get_slots(formation)
    eligible = [p for p in candidate_pool if p.player_id not in opponent_squad_player_ids]

    model = cp_model.CpModel()
    x: dict[tuple[str, str], cp_model.IntVar] = {}

    for slot in slots:
        for player in eligible:
            if player.position_group != slot.position_group:
                continue
            x[(slot.slot_id, player.player_id)] = model.new_bool_var(f"x_{slot.slot_id}_{player.player_id}")

    for slot in slots:
        vars_for_slot = [v for (sid, _pid), v in x.items() if sid == slot.slot_id]
        if not vars_for_slot:
            return None  # no eligible player at all for this slot -> infeasible
        model.add_exactly_one(vars_for_slot)

    player_ids = {pid for (_sid, pid) in x}
    for pid in player_ids:
        vars_for_player = [v for (_sid, p), v in x.items() if p == pid]
        model.add_at_most_one(vars_for_player)

    price_by_id = {p.player_id: p.price_eur for p in eligible}
    model.add(sum(price_by_id[pid] * v for (_sid, pid), v in x.items()) <= BUDGET_EUR)

    nat_by_id = {p.player_id: p.nationality for p in eligible}
    nationalities = {p.nationality for p in eligible}
    for nat in nationalities:
        vars_for_nat = [v for (_sid, pid), v in x.items() if nat_by_id[pid] == nat]
        if vars_for_nat:
            model.add(sum(vars_for_nat) <= NATIONALITY_LIMIT)

    players_by_id = {p.player_id: p for p in eligible}
    objective_terms = []
    for (slot_id, pid), var in x.items():
        slot = next(s for s in slots if s.slot_id == slot_id)
        fit = role_fit_score(slot.position_code, players_by_id[pid])
        objective_terms.append(round(fit * 100) * var)
    model.maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assignments: dict[str, PlayerCard] = {}
    for (slot_id, pid), var in x.items():
        if solver.value(var) == 1:
            assignments[slot_id] = players_by_id[pid]

    return Lineup(formation=formation, assignments=assignments)


def manager_score(
    user_lineup: Lineup,
    opponent: TeamProfile,
    candidate_pool: list[PlayerCard],
    opponent_squad_player_ids: set[str],
    rating_model: RatingModel,
) -> ManagerScoreResult:
    user_rating = rating_model.rate(user_lineup, opponent).overall
    best_lineup = find_optimal_lineup(user_lineup.formation, candidate_pool, opponent_squad_player_ids)
    if best_lineup is None:
        return ManagerScoreResult(user_rating=user_rating, best_rating=user_rating, manager_score=1.0)

    best_rating = rating_model.rate(best_lineup, opponent).overall
    score = user_rating / best_rating if best_rating > 0 else 1.0
    return ManagerScoreResult(
        user_rating=round(user_rating, 1),
        best_rating=round(best_rating, 1),
        manager_score=round(min(1.5, score), 3),
    )
