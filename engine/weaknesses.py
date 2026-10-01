"""The full weakness rule catalogue. Implements docs/DESIGN.md section 7.4.

Every rule returns zero or more Weakness objects, each with a type, zone, severity in
[0, 1] and the evidence stats behind it (CLAUDE.md: numbers always come from engine/,
never invented by the LLM).
"""

from __future__ import annotations

from config.game import WEAKNESS_THRESHOLDS
from engine.matchups import zone_mismatches
from engine.schemas import Lineup, TeamProfile, Weakness
from engine.team_profile import press_intensity, zone_threat_map
from engine.zones import slot_defs


def _zone_mismatch_weaknesses(lineup: Lineup, opponent: TeamProfile) -> list[Weakness]:
    out: list[Weakness] = []
    threshold = WEAKNESS_THRESHOLDS["zone_mismatch"]
    for m in zone_mismatches(lineup, opponent):
        if m.mismatch_score <= threshold or not m.affected_slots:
            continue
        severity = min(1.0, m.mismatch_score / 50.0)
        out.append(
            Weakness(
                type="zone_mismatch",
                vertical_zone=m.vertical_zone,
                horizontal_zone=m.horizontal_zone,
                severity=round(severity, 2),
                evidence={"threat": m.threat, "zone_strength": m.zone_strength},
                affected_slots=m.affected_slots,
                description=(
                    f"Opponent threat {m.threat:.0f} in the {m.horizontal_zone} "
                    f"{m.vertical_zone} third vs your {m.zone_strength:.0f}-rated cover there."
                ),
            )
        )
    return out


def _missing_role_weakness(lineup: Lineup, opponent: TeamProfile) -> list[Weakness]:
    if opponent.ppda == 0 or press_intensity(opponent.ppda) >= 40:
        return []  # opponent isn't a patient possession side
    defs = slot_defs(lineup.formation)
    has_destroyer = any(
        defs[slot_id].position_code in {"DM", "CM"}
        and player.role_fit.get("ball_winning_dm", player.ability_score) >= 75
        for slot_id, player in lineup.assignments.items()
        if slot_id in defs
    )
    if has_destroyer:
        return []
    return [
        Weakness(
            type="missing_role",
            vertical_zone="mid",
            horizontal_zone="center",
            severity=0.6,
            evidence={"opponent_press_intensity": press_intensity(opponent.ppda)},
            affected_slots=[],
            description="No ball-winning midfielder to press a patient possession side.",
        )
    ]


def _aerial_deficit_weakness(lineup: Lineup, opponent: TeamProfile) -> list[Weakness]:
    if opponent.aerial <= WEAKNESS_THRESHOLDS["aerial_risk"]:
        return []
    defs = slot_defs(lineup.formation)
    aerial_scores = [
        player.per90.get("aerial_win_pct", 50.0)
        for slot_id, player in lineup.assignments.items()
        if slot_id in defs and defs[slot_id].position_code in {"CB", "GK"}
    ]
    avg_aerial = sum(aerial_scores) / len(aerial_scores) if aerial_scores else 50.0
    if avg_aerial >= 60.0:
        return []
    return [
        Weakness(
            type="aerial_deficit",
            vertical_zone="def",
            horizontal_zone="center",
            severity=round(min(1.0, (opponent.aerial - 60) / 40), 2),
            evidence={"opponent_aerial": opponent.aerial, "your_aerial_win_pct": avg_aerial},
            affected_slots=[
                sid
                for sid, p in lineup.assignments.items()
                if sid in defs and defs[sid].position_code in {"CB", "GK"}
            ],
            description=f"Opponent aerial threat {opponent.aerial:.0f} vs your {avg_aerial:.0f}% win rate.",
        )
    ]


def _press_resistance_weakness(lineup: Lineup, opponent: TeamProfile) -> list[Weakness]:
    intensity = press_intensity(opponent.ppda)
    if intensity < 75:
        return []
    defs = slot_defs(lineup.formation)
    mid_slots = {
        sid: p for sid, p in lineup.assignments.items() if sid in defs and defs[sid].vertical_zone == "mid"
    }
    if not mid_slots:
        return []
    avg_resistance = sum(
        p.per90.get("press_resistance", p.ability_score) for p in mid_slots.values()
    ) / len(mid_slots)
    if avg_resistance >= WEAKNESS_THRESHOLDS["press_resistance"]:
        return []
    return [
        Weakness(
            type="low_press_resistance",
            vertical_zone="mid",
            horizontal_zone="center",
            severity=round(min(1.0, (WEAKNESS_THRESHOLDS["press_resistance"] - avg_resistance) / 30), 2),
            evidence={"opponent_press_intensity": intensity, "your_press_resistance": avg_resistance},
            affected_slots=list(mid_slots),
            description=f"Opponent presses at {intensity:.0f}; your pivot resists at {avg_resistance:.0f}.",
        )
    ]


def _set_piece_weakness(lineup: Lineup, opponent: TeamProfile) -> list[Weakness]:
    if opponent.set_piece_threat <= WEAKNESS_THRESHOLDS["set_piece_threat"]:
        return []
    defs = slot_defs(lineup.formation)
    def_slots = {
        sid: p for sid, p in lineup.assignments.items() if sid in defs and defs[sid].vertical_zone == "def"
    }
    if not def_slots:
        return []
    best_aerial = max(p.per90.get("aerial_win_pct", 50.0) for p in def_slots.values())
    if best_aerial >= 65.0:
        return []
    return [
        Weakness(
            type="set_piece_vulnerability",
            vertical_zone="def",
            horizontal_zone="center",
            severity=round(min(1.0, (opponent.set_piece_threat - 60) / 40), 2),
            evidence={"opponent_set_piece_threat": opponent.set_piece_threat, "your_best_aerial": best_aerial},
            affected_slots=list(def_slots),
            description=f"Set-piece threat {opponent.set_piece_threat:.0f}; no dominant aerial presence at the back.",
        )
    ]


def _out_of_position_weaknesses(lineup: Lineup) -> list[Weakness]:
    defs = slot_defs(lineup.formation)
    out: list[Weakness] = []
    for slot_id, player in lineup.assignments.items():
        if slot_id not in defs or not player.natural_position_codes:
            continue
        if defs[slot_id].position_code not in player.natural_position_codes:
            out.append(
                Weakness(
                    type="out_of_position",
                    vertical_zone=defs[slot_id].vertical_zone,
                    horizontal_zone=defs[slot_id].horizontal_zone,
                    severity=0.35,
                    evidence={},
                    affected_slots=[slot_id],
                    description=(
                        f"{player.name} is naturally {'/'.join(player.natural_position_codes)}, "
                        f"not {defs[slot_id].position_code}."
                    ),
                )
            )
    return out


def _footedness_imbalance_weakness(lineup: Lineup) -> list[Weakness]:
    defs = slot_defs(lineup.formation)
    lb = next((p for sid, p in lineup.assignments.items() if sid in defs and defs[sid].position_code == "LB"), None)
    rb = next((p for sid, p in lineup.assignments.items() if sid in defs and defs[sid].position_code == "RB"), None)
    if lb is None or rb is None or lb.preferred_foot != rb.preferred_foot:
        return []
    return [
        Weakness(
            type="footedness_imbalance",
            vertical_zone="def",
            horizontal_zone="center",
            severity=0.25,
            evidence={},
            affected_slots=[],
            description=f"Both full-backs are {lb.preferred_foot}-footed — same-side overlaps and crossing angles suffer.",
        )
    ]


def _low_confidence_weaknesses(lineup: Lineup) -> list[Weakness]:
    defs = slot_defs(lineup.formation)
    threshold = WEAKNESS_THRESHOLDS["low_confidence"]
    out: list[Weakness] = []
    for slot_id, player in lineup.assignments.items():
        if player.confidence < threshold:
            out.append(
                Weakness(
                    type="low_confidence_player",
                    vertical_zone=defs[slot_id].vertical_zone if slot_id in defs else "mid",
                    horizontal_zone=defs[slot_id].horizontal_zone if slot_id in defs else "center",
                    severity=round(min(1.0, (threshold - player.confidence) / threshold + 0.3), 2),
                    evidence={"confidence": player.confidence},
                    affected_slots=[slot_id],
                    description=f"{player.name}'s stats come from limited coverage — rating may be unreliable.",
                )
            )
    return out


def _budget_misallocation_weaknesses(lineup: Lineup, opponent: TeamProfile) -> list[Weakness]:
    defs = slot_defs(lineup.formation)
    total_spend = sum(p.price_eur for p in lineup.assignments.values())
    if total_spend == 0:
        return []
    zone_threats = zone_threat_map(opponent)
    threats = {
        v: sum(t for (vert, _h), t in zone_threats.items() if vert == v) for v in ("def", "mid")
    }
    total_threat = sum(threats.values()) or 1.0

    out: list[Weakness] = []
    for vertical in ("def", "mid"):
        spend = sum(
            p.price_eur
            for sid, p in lineup.assignments.items()
            if sid in defs and defs[sid].vertical_zone == vertical
        )
        spend_share = spend / total_spend
        threat_share = threats[vertical] / total_threat
        gap = threat_share - spend_share
        if gap > 0.15:
            out.append(
                Weakness(
                    type="budget_misallocation",
                    vertical_zone=vertical,
                    horizontal_zone="center",
                    severity=round(min(1.0, gap), 2),
                    evidence={"spend_share": round(spend_share, 2), "threat_share": round(threat_share, 2)},
                    affected_slots=[],
                    description=(
                        f"{vertical.title()} carries {threat_share:.0%} of the opponent's threat but only "
                        f"{spend_share:.0%} of your budget."
                    ),
                )
            )
    return out


def find_weaknesses(lineup: Lineup, opponent: TeamProfile) -> list[Weakness]:
    weaknesses = (
        _zone_mismatch_weaknesses(lineup, opponent)
        + _missing_role_weakness(lineup, opponent)
        + _aerial_deficit_weakness(lineup, opponent)
        + _press_resistance_weakness(lineup, opponent)
        + _set_piece_weakness(lineup, opponent)
        + _out_of_position_weaknesses(lineup)
        + _footedness_imbalance_weakness(lineup)
        + _low_confidence_weaknesses(lineup)
        + _budget_misallocation_weaknesses(lineup, opponent)
    )
    return sorted(weaknesses, key=lambda w: w.severity, reverse=True)
