# Progress

## Environment notes (read this first)

- Docker Desktop's Linux engine would not start in the sandbox this was built in (no
  WSL2/Hyper-V backend reachable). Every Postgres+pgvector and self-hosted Langfuse
  piece of this repo is real and written to run (`docker-compose.yml`, the Alembic
  migration, the Langfuse SDK hooks) but was never exercised against a live container —
  only against the SQLite fallback described in `docs/DECISIONS.md`.
- `make` isn't installed on this machine either, so `Makefile` targets were verified by
  running their underlying commands directly (`pytest`, `uvicorn ...`, `alembic ...`).
- Python 3.14 is what's on this box; pyproject declares `>=3.11`. Everything installed
  clean, including `torch`/`sentence-transformers`, so there's no known compatibility gap.

## Phase 1 — Data foundation

**The real Transfermarkt/Understat pulls were replaced with a synthetic generator**
(`pipeline/synthetic_source.py`) — see docs/DECISIONS.md for why. It emits two
independent, intentionally-disagreeing "sources" (perturbed names, only a subset of
clubs covered by the "Understat" side) so `pipeline/id_resolution.py`'s normalised
name + DOB + club matching, fuzzy fallback and unresolved-case CSV all do real work
against real disagreement, not a no-op.

Built: `pipeline/synthetic_source.py`, `pipeline/id_resolution.py`, `pipeline/ingest.py`
(loads players/clubs/national_teams/player_id_map/squads/player_stats_season),
`pipeline/data_quality.py`, `db/bootstrap.py` (SQLite/dev table creation).

`python -m pipeline.run_all` against a fresh SQLite db (seed 42): 830 players, 10 UCL
club squads (25 each), 12 WC2026 national squads (23 each, all from real nationality
pools so they're genuinely eligible-and-excluded rather than placeholder), 697/830
matched to "Understat" stats (0 unresolved after fixing the uniqueness bug below).

**Bug found and fixed during this phase**: the first id_resolution pass let two
different Understat records both claim the same Transfermarkt player when several
squad-mates shared a date of birth — a real `UNIQUE constraint failed` on
`player_id_map.player_id`. Fixed by tracking claimed `tm_id`s and skipping them for
subsequent matches (`pipeline/id_resolution.py::resolve`), which also matches reality:
a real player has exactly one Understat identity, never two.

## Phase 2 — Ability + pricing

Built: `pipeline/features.py` (per-90s, position-relative percentiles via
`scipy.stats.rankdata`, ability score, confidence flag, style vector, on-demand
role-fit via `compute_role_fit`), `pipeline/pricing.py` (XGBoost de-biased pricing).

**Bug found and fixed**: `ABILITY_WEIGHTS`/`ROLE_FIT_FORMULAS` keys (e.g. `"xg_pct"`)
didn't match the percentile dict's actual keys (`"xg_per90_pct"`), so every lookup
silently fell back to a constant 50.0 — forwards' ability scores were *all exactly
50.0* regardless of real quality (correlation with the synthetic ground-truth quality
was 0.109 for FW vs 0.83+ for defenders, where the key names happened to partially
collide and so partially worked). This is exactly the kind of silent-wrong-number bug
CLAUDE.md rule 1 exists to catch, and it would never have shown up as a crash — only
as a bad top-50 list. Fixed by stripping the `_per90` suffix consistently when
building percentile keys. Verified with `tests/test_pipeline.py`'s correlation
assertions (per position group, not just overall) so this class of bug fails loudly
next time.

**Budget sanity check, run as instructed rather than silently tuned**: the first
market-value curve let a full top-2%-ability XI fit under EUR500M (`full_elite_xi_fits
_under_budget: True`), which the Phase 2 prompt says to report and adjust rather than
hide. Re-tuned the synthetic market-value curve's exponent/scale (`pipeline/
synthetic_source.py`, documented in its own comment) so the top price is ~EUR150M and
the budget now affords roughly 2 elite players alongside 8 median starters —
close to DESIGN.md's "~3 elite + 8 good" target. Pricing MAE: ~40% of mean market
value on held-out data, which is close to the synthetic generator's own built-in
+/-30% multiplicative noise floor, not a claim about real-world pricing accuracy.

Manual check done: the top-50 price list is dominated by the highest true_quality
synthetic players across all positions (not just one group), and young-vs-old /
different-league players price sensibly relative to their ability score.

## Phase 3 — Engine core

Built: `engine/rules.py`, `engine/team_profile.py`, `engine/rating.py` (v1 + the
`RatingModel` interface), `engine/matchups.py`, `engine/weaknesses.py` (full 9-rule
catalogue from DESIGN.md 7.4), `engine/swaps.py`, `engine/optimizer.py` (OR-Tools
CP-SAT), `engine/demo_fixtures.py` (the Brazil scenario from the Lineup Lab mockup —
`strong` / `weak_leftback` / `all_attack` 4-3-3 lineups), `engine/analyse.py` (CLI).

**Analysis JSON schema**: `engine.schemas.LineupAnalysis` — session_id, formation,
rating (sub-ratings + overall), weaknesses (list), swaps_by_weakness (keyed by
`"{type}:{vertical}:{horizontal}"`), manager_score, validation, win_draw_loss.

Verified: `python -m pytest tests/ -q` — 35 passed, including two Hypothesis
property tests (`tests/test_properties.py`) that generate randomised candidate pools
and assert the optimizer and the swap suggester never hand back a lineup that fails
`rules.validate_lineup`. `ruff check .` and `mypy engine --strict` are both clean.

Manual check done: `python -m engine.analyse --demo --scenario weak_leftback` finds
the planted left-back/Martins zone mismatch; `--scenario strong` doesn't; swap
suggestions for that weakness are all real, priced, budget-aware alternatives.

## Phase 4 — Scenarios

Built: `engine/counter.py` (substitution / reposition / formation-change moves, beam
width 5, max 2 changes/round, max 3 rounds, fully deterministic — no RNG at all) and
`engine/simulation.py` (Poisson Monte Carlo, ET, penalties, two-leg aggregate for UCL).

A real modelling gap worth flagging: v1's "expected goals" come from the rating
sub-scores via a hand-picked formula (`engine/simulation.py::expected_goals`), not a
trained xG model — Phase 7's rating v2 is explicitly where DESIGN.md intends a real
historical-data model to replace this, through the same `RatingModel` interface.

Verified: counter never fields a player outside the opponent's squad, the round cap
raises past 3, same seed -> byte-identical output, simulation runs in well under the
1s budget, and knockout ties always get resolved (ET, then penalties, and a penalty
shootout is re-rolled until it produces a winner).

## Phase 5 — AI layer

*(filled in once built)*

## Phase 6 — API + frontend

*(filled in once built)*

## Phase 7 — Production

Not attempted beyond CI config and eval scaffolding — no deployment, per instruction.
