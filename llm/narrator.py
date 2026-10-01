"""Coach report / match report prose. docs/DESIGN.md section 9, point 1: input is
engine JSON + retrieved context; the LLM writes prose around placeholders that code
has already filled with engine numbers -- never the other way round.
"""

from __future__ import annotations

from engine.schemas import LineupAnalysis, SimulationResult
from llm.provider import Provider
from llm.validator import ValidatedText, validate_and_fix


def _coach_report_template(analysis: LineupAnalysis, team_name: str) -> str:
    r = analysis.rating
    win, draw, loss = analysis.win_draw_loss
    lines = [
        f"Facing {team_name}, your {analysis.formation} rates {r.overall:.1f}/100 overall "
        f"(attack {r.sub_ratings.attack:.1f}, midfield {r.sub_ratings.midfield_control:.1f}, "
        f"defence {r.sub_ratings.defence:.1f}, matchup {r.sub_ratings.matchup:.1f}).",
        f"Simulated outcome: {win:.1f}% win, {draw:.1f}% draw, {loss:.1f}% loss.",
        f"Manager score: {analysis.manager_score.manager_score * 100:.1f}% of the best possible lineup "
        f"under these constraints.",
    ]
    if analysis.weaknesses:
        top = analysis.weaknesses[0]
        lines.append(
            f"Biggest concern: {top.description} (severity {top.severity * 100:.0f}%)."
        )
        key = f"{top.type}:{top.vertical_zone}:{top.horizontal_zone}"
        swaps = analysis.swaps_by_weakness.get(key, [])
        if swaps:
            s = swaps[0]
            sign = "+" if s.price_delta_eur >= 0 else ""
            lines.append(
                f"Top suggestion: {s.out_player_name} -> {s.in_player.name} "
                f"({s.rating_gain:+.1f} rating, {sign}EUR{s.price_delta_eur:,})."
            )
    else:
        lines.append("No significant weaknesses flagged against this opponent.")

    if not analysis.validation.valid:
        lines.append(
            f"Note: this lineup isn't legal yet ({len(analysis.validation.violations)} rule violation(s))."
        )
    return " ".join(lines)


def _coach_report_allowed_values(analysis: LineupAnalysis) -> set[float]:
    r = analysis.rating
    win, draw, loss = analysis.win_draw_loss
    values = {
        r.overall, r.sub_ratings.attack, r.sub_ratings.midfield_control, r.sub_ratings.defence,
        r.sub_ratings.matchup, r.sub_ratings.cohesion, r.sub_ratings.balance,
        win, draw, loss, round(analysis.manager_score.manager_score * 100, 1),
        float(analysis.validation.budget_spent_eur), float(analysis.validation.budget_left_eur),
        float(len(analysis.validation.violations)),
    }
    for d in analysis.formation.split("-"):
        values.add(float(d))
    for w in analysis.weaknesses:
        values.add(round(w.severity * 100, 0))
        for v in w.evidence.values():
            values.add(float(v))
            values.add(round(float(v), 0))
    for swaps in analysis.swaps_by_weakness.values():
        for s in swaps:
            values.update({s.rating_gain, float(s.price_delta_eur), float(abs(s.price_delta_eur))})
    return values


def narrate_coach_report(analysis: LineupAnalysis, team_name: str, provider: Provider) -> ValidatedText:
    template = _coach_report_template(analysis, team_name)
    allowed = _coach_report_allowed_values(analysis)
    system = (
        "You are a football coach giving a tactical debrief. Restyle the following "
        "facts into natural, confident prose. Do not introduce, change, round "
        "differently, or drop any number -- every figure must appear exactly as given."
    )
    first = provider.complete(template, system=system)
    return validate_and_fix(
        first, allowed, regenerate=lambda: provider.complete(template, system=system), fallback_text=template
    )


def _match_report_template(sim: SimulationResult, opponent_name: str) -> str:
    us, them = sim.narrative_score
    lines = [f"Full time vs {opponent_name}: {us}-{them}."]
    if sim.went_to_extra_time:
        lines.append("It went to extra time.")
    if sim.went_to_penalties and sim.penalty_score:
        lines.append(f"Settled on penalties, {sim.penalty_score[0]}-{sim.penalty_score[1]}.")
    for event in sim.narrative_events:
        side = "You" if event.side == "user" else opponent_name
        lines.append(f"{event.minute}': {side} - {event.player_name} ({event.type}).")
    return " ".join(lines)


def _match_report_allowed_values(sim: SimulationResult) -> set[float]:
    values = {float(sim.narrative_score[0]), float(sim.narrative_score[1])}
    if sim.penalty_score:
        values.update({float(sim.penalty_score[0]), float(sim.penalty_score[1])})
    for event in sim.narrative_events:
        values.add(float(event.minute))
    return values


def narrate_match_report(sim: SimulationResult, opponent_name: str, provider: Provider) -> ValidatedText:
    template = _match_report_template(sim, opponent_name)
    allowed = _match_report_allowed_values(sim)
    system = (
        "You are writing a short match report. Restyle the following facts into "
        "natural prose. Do not introduce, change or drop any number, minute or score."
    )
    first = provider.complete(template, system=system)
    return validate_and_fix(
        first, allowed, regenerate=lambda: provider.complete(template, system=system), fallback_text=template
    )
