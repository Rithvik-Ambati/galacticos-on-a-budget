"""The single place game rules are enforced. CLAUDE.md rule 2: never duplicate this logic
elsewhere. Implements docs/DESIGN.md section 1 and the Phase 3 prompt's rules.py spec.
"""

from __future__ import annotations

from collections import Counter

from config.game import BUDGET_EUR, FORMATIONS, NATIONALITY_LIMIT, SQUAD_SIZE, Slot
from engine.schemas import EligibilityResult, Lineup, PlayerCard, RuleViolation, ValidationResult


def get_slots(formation: str) -> tuple[Slot, ...]:
    if formation not in FORMATIONS:
        raise ValueError(f"Unknown formation: {formation!r}. Allowed: {sorted(FORMATIONS)}")
    return FORMATIONS[formation]


def slot_by_id(formation: str, slot_id: str) -> Slot:
    for slot in get_slots(formation):
        if slot.slot_id == slot_id:
            return slot
    raise ValueError(f"Unknown slot {slot_id!r} for formation {formation!r}")


def validate_lineup(
    lineup: Lineup,
    opponent_squad_player_ids: set[str],
    *,
    require_complete: bool = True,
) -> ValidationResult:
    """Validate budget, nationality limit, opponent exclusion, duplicates and slot/position fit.

    With require_complete=False (used by the live "build" screen while the user is still
    picking players), an empty slot is not itself a violation — everything else still is.
    """
    violations: list[RuleViolation] = []

    try:
        slots = get_slots(lineup.formation)
    except ValueError as exc:
        return ValidationResult(
            valid=False,
            violations=[RuleViolation(code="unknown_formation", message=str(exc))],
        )
    slot_ids = {s.slot_id for s in slots}

    for slot_id in lineup.assignments:
        if slot_id not in slot_ids:
            violations.append(
                RuleViolation(
                    code="unknown_slot",
                    message=f"{slot_id} is not part of formation {lineup.formation}",
                    slot_id=slot_id,
                )
            )

    filled_slots = len(lineup.assignments)
    if require_complete and filled_slots < SQUAD_SIZE:
        missing = sorted(slot_ids - set(lineup.assignments))
        violations.append(
            RuleViolation(
                code="incomplete_lineup",
                message=f"{SQUAD_SIZE - filled_slots} slot(s) still empty: {', '.join(missing)}",
            )
        )

    seen_players: Counter[str] = Counter()
    for assigned_player in lineup.assignments.values():
        seen_players[assigned_player.player_id] += 1
    for pid, count in seen_players.items():
        if count > 1:
            violations.append(
                RuleViolation(
                    code="duplicate_player",
                    message=f"Player {pid} is assigned to {count} slots",
                )
            )

    budget_spent = sum(p.price_eur for p in lineup.assignments.values())
    if budget_spent > BUDGET_EUR:
        violations.append(
            RuleViolation(
                code="budget_exceeded",
                message=f"€{budget_spent:,} spent exceeds the €{BUDGET_EUR:,} budget",
            )
        )

    nationality_counts = Counter(p.nationality for p in lineup.assignments.values())
    for nat, count in nationality_counts.items():
        if count > NATIONALITY_LIMIT:
            violations.append(
                RuleViolation(
                    code="nationality_limit",
                    message=f"{nat} has {count} players, limit is {NATIONALITY_LIMIT}",
                )
            )

    for slot_id, player in lineup.assignments.items():
        if player.player_id in opponent_squad_player_ids:
            violations.append(
                RuleViolation(
                    code="opponent_squad_exclusion",
                    message=f"{player.name} is in the opponent's squad",
                    slot_id=slot_id,
                )
            )

    slots_by_id = {s.slot_id: s for s in slots}
    for slot_id, player in lineup.assignments.items():
        slot = slots_by_id.get(slot_id)
        if slot is not None and player.position_group != slot.position_group:
            violations.append(
                RuleViolation(
                    code="position_mismatch",
                    message=(
                        f"{player.name} ({player.position_group}) can't fill a "
                        f"{slot.position_group} slot ({slot_id})"
                    ),
                    slot_id=slot_id,
                )
            )

    return ValidationResult(
        valid=len(violations) == 0,
        violations=violations,
        budget_spent_eur=budget_spent,
        budget_left_eur=BUDGET_EUR - budget_spent,
        nationality_counts=dict(nationality_counts),
        filled_slots=filled_slots,
    )


def eligibility(
    player: PlayerCard,
    lineup: Lineup,
    opponent_squad_player_ids: set[str],
    *,
    slot_id: str | None = None,
) -> EligibilityResult:
    """Used by the player-search endpoint to grey out ineligible players with a reason."""

    if player.player_id in lineup.player_ids():
        return EligibilityResult(eligible=False, reason="Already in your lineup")

    if player.player_id in opponent_squad_player_ids:
        return EligibilityResult(eligible=False, reason="In opponent's squad")

    current_counts = Counter(p.nationality for p in lineup.assignments.values())
    outgoing = lineup.assignments.get(slot_id) if slot_id else None
    if outgoing is not None and outgoing.nationality == player.nationality:
        pass  # replacing a player of the same nationality never changes the count
    elif current_counts[player.nationality] >= NATIONALITY_LIMIT:
        return EligibilityResult(
            eligible=False,
            reason=f"Nationality limit reached — {player.nationality} "
            f"{current_counts[player.nationality]}/{NATIONALITY_LIMIT}",
        )

    spent = sum(p.price_eur for p in lineup.assignments.values())
    if outgoing is not None:
        spent -= outgoing.price_eur
    budget_left = BUDGET_EUR - spent
    if player.price_eur > budget_left:
        return EligibilityResult(
            eligible=False,
            reason=f"Costs €{player.price_eur:,}, only €{budget_left:,} left",
        )

    if slot_id is not None:
        try:
            slot = slot_by_id(lineup.formation, slot_id)
        except ValueError as exc:
            return EligibilityResult(eligible=False, reason=str(exc))
        if player.position_group != slot.position_group:
            return EligibilityResult(
                eligible=False,
                reason=f"{player.position_group} can't fill a {slot.position_group} slot",
            )

    return EligibilityResult(eligible=True)
