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

*(filled in once built)*

## Phase 2 — Ability + pricing

*(filled in once built)*

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
