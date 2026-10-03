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

Built: `pipeline/documents.py` + `pipeline/team_profiles.py` (derives TeamProfile rows
from squad features -- no match-event source exists, see docs/DECISIONS.md),
`rag/bm25.py`, `rag/dense.py`, `rag/fusion.py` (RRF), `rag/rerank.py`, `rag/retriever.py`
(full hybrid pipeline with rewrite-and-retry + fallback), `rag/embeddings.py`,
`llm/provider.py` (Stub + Anthropic), `llm/narrator.py`, `llm/validator.py`,
`llm/sql_tool.py`, `graph/state.py`, `graph/nodes.py`, `graph/chat_tools.py`,
`graph/graph.py`. Checkpointer is `MemorySaver` (docs/DECISIONS.md — no live Postgres
to test `AsyncPostgresSaver` against).

**Real bugs found and fixed while wiring this together** (in the order hit):
1. `graph/state.py`'s `GameState` TypedDict didn't declare the key the `validate` node
   was writing (`_validation_ok`) — LangGraph silently drops updates to undeclared
   channels, so the router never saw the result and *always* looped back to `build`,
   even for a perfectly valid lineup. Renamed to a declared `validation_ok` field.
   Lesson: every key a node returns must be declared on the TypedDict, or the write is
   silently a no-op — there's no error, just state that never changes.
2. After a `formation_change` counter move, the opponent's lineup legitimately has a
   different formation (e.g. 3-5-2's `CB3` slot), but `graph/nodes.py` hard-coded
   `"4-2-3-1"` when rehydrating the opponent lineup on the *next* round, so
   `engine/counter.py` crashed with `KeyError: 'CB3'` looking up a slot that doesn't
   exist in the hard-coded formation. Added `opponent_formation` to `GameState` and
   threaded it through `draw`/`opponent_counter` instead of hard-coding it.
3. `llm/validator.py`'s number-extraction regex read a bare `-` as a minus sign
   anywhere, so `"4-3-3"` (a formation) parsed as `[4, -3, -3]` and `"2-1"` (a score)
   as `[2, -1]` — both wrong, and both appear in every single narrated report. This
   made `narrate_coach_report`/`narrate_match_report` fail validation *even with the
   identity-function StubProvider*, i.e. even when the text couldn't possibly contain
   an invented number. Fixed by only treating `-` as a sign when it's at the start of
   the text or after whitespace. Caught immediately because the stub-provider test
   asserted `result.passed` rather than just checking the text was non-empty — a
   weaker test would have shipped this silently always-falling-back-to-template.
4. `_coach_report_allowed_values` didn't include the weakness `evidence` numbers or
   the formation's own digits, so even after fixing the regex, legitimately-templated
   numbers like "62" (a threat score) still failed validation. Both bugs together mean
   the validator was *always* triggering the fallback path for the coach report before
   this phase's tests were written.
5. `Bm25Index(doc_ids=[], texts=[])` crashed with `ZeroDivisionError` inside
   `rank_bm25` (average-doc-length calc divides by corpus size) — an empty corpus is a
   completely normal state (e.g. documents not built yet), not an edge case to skip
   testing.

Verified: `python -m pytest tests/test_llm.py tests/test_rag.py -q` (19 tests) plus
the full `test_graph.py` integration suite below.

## Phase 5b — LangGraph integration (folded into Phase 5)

Three end-to-end tests in `tests/test_graph.py` drive a real `MemorySaver`-checkpointed
session through every interrupt: draw -> build (resume with an `engine.optimizer`
-generated, budget-valid lineup) -> validate -> analyse -> narrate_report ->
user_decision -> lock_in -> simulate -> narrate_match -> chat (resume a question,
then resume `{"end": True}`) -> graph ends cleanly (`graph.get_state(config).next == ()`).
A second test drives the counter loop past its 3-round cap and confirms it stops
there and falls through to `simulate`. A third resumes `build` with a deliberately
over-budget lineup and confirms it bounces back to `build` rather than proceeding.

## Phase 6 — API + frontend

Built: `api/main.py`, `api/routers.py`, `api/schemas.py`, `api/deps.py` (all 11
endpoints from DESIGN.md section 11, including an SSE `/chat` that streams the
narrated answer word-by-word -- see docs/DECISIONS.md on what "streamed" means with
a stub LLM provider), and a full `frontend/` (React + Vite + TypeScript; plain CSS
instead of Tailwind, see docs/DECISIONS.md) implementing all 8 screens from
DESIGN.md section 2, wired to the real API.

**Verified two ways**: `tests/test_api.py` drives a complete session over real HTTP
semantics (httpx's ASGI transport) -- draw, scout, search, validate, analyse,
lock-in, SSE chat, chat/end, final state -- plus a 422 case (over-budget lineup) and
a 409 case (simulate before lock-in). Then, separately, a real browser session
(`npm run dev` + `uvicorn api.main:app --reload`) played two complete matches
end-to-end by hand: Welcome -> Draw -> Scouting -> Build XI (manually searching,
filtering by affordability, and assigning all 11 players) -> Coach's Report (real
weaknesses, real swap suggestions, real pitch highlighting) -> Match Day -> Match
Report -> chat. Final score first match: 3-1 win vs England, manager score 98%.

**Real bugs found and fixed while doing the manual browser playthrough** (this is
exactly why CLAUDE.md asks for it, not just automated tests):
1. A **frontend race condition**: clicking a pitch slot kicks off a new player
   search, but the previous search's results stayed on screen until the new ones
   arrived. Clicking fast enough landed a click on a stale row from the *previous*
   slot's results, silently assigning the same player to two different slots (the
   backend's own `duplicate_player` rule correctly blocked analysis, but the UI
   should never have offered it). Fixed in `frontend/src/screens/BuildXI.tsx` two
   ways: clear `results` the instant `activeSlot` changes, and make `pickPlayer`
   itself refuse to let the same player occupy two slots, regardless of how it got
   clicked.
2. **A real product gap, not just a bug**: `load_candidate_pool`'s pool is ordered
   by ability descending and capped at 400 -- the top of that list is almost always
   unaffordable once the budget is half spent, and there was no way to search by
   price. Added `max_price_eur` to `GET /players/search` and an "Affordable only"
   toggle in the UI (defaulting on) that passes the player's own remaining budget
   (plus whatever the slot being replaced already costs). Without this, a careful
   player can paint themselves into a corner with no legal 11th pick.
3. **Dev-workflow trap, not a code bug**: the `max_price_eur` fix above appeared to
   not work at all on first browser test -- because the API server had been started
   without `--reload`, so it was still running the pre-fix code. Confirmed via
   `read_network_requests` that the request *did* carry the new parameter and the
   server still ignored it, which pointed straight at stale server code rather than
   a client bug. Restarting with `--reload` (as the `Makefile`'s `api` target already
   specifies) fixed it immediately. Documented here because it's a trap this project
   is especially exposed to: lots of small `api/` edits made directly against a
   long-running manually-started server.
4. Restarting that server for fix #3 above also demonstrated
   docs/DECISIONS.md's MemorySaver caveat firsthand: the in-progress browser
   session's graph state vanished (the DB row for the session still existed, so
   `/sessions/{id}` didn't 404, but `/lineup/analyse` correctly reported "no opponent
   yet" since the graph had no memory of the earlier `/draw` call). Not a bug --
   exactly the documented behavior -- but worth recording that it was *hit*, not just
   theorized, which is the strongest argument for prioritizing the Postgres
   checkpointer before any real deployment.
5. Coach/match report prose showed the raw internal id (`"vs nt_ENG"`) instead of a
   readable name. Added `pipeline/to_engine.py::load_team_name` and used it at both
   narration call sites in `graph/nodes.py`.

Manual check done (desktop viewport in the browser pane): all 8 screens render
correctly with real data; nationality/opponent-exclusion eligibility correctly
varies per opponent (the same player who is "In opponent's squad" against Uruguay is
freely eligible against France); budget, nationality counts and live pitch rendering
all stay in sync with the backend on every pick.

## Phase 7 — Production

Built: `evals/retrieval_eval.py` (Recall@10/MRR/nDCG, ablated across BM25/dense/
hybrid/hybrid+rerank via the new `rag/retriever.py::retrieve_ablation`),
`evals/numeric_eval.py` (validator pass rate — needs no golden set, since "correct"
here is mechanically checkable against the engine's own numbers),
`evals/run_all.py` (`make eval`; writes `evals/reports/baseline.json` and an
`EvalRun` DB row), `.github/workflows/{ci,nightly-eval,weekly-pipeline}.yml`,
production `Dockerfile` / `frontend/Dockerfile` / `docker-compose.prod.yml`, and the
top-level `README.md` with real measured numbers (see the README itself, not
reproduced here).

**Explicitly not attempted, each for a specific documented reason** (not oversight):
- Retrieval eval and RAGAS faithfulness both need a human-written golden set
  (CLAUDE.md: "Golden eval sets in `evals/golden/` are written by the human. Do not
  generate or edit expected answers.") — `evals/golden/{retrieval,chat}.jsonl` are
  empty templates with a format README; the runners are tested against that empty
  state, not against fabricated golden data.
- Rating v2 needs real historical match results to train an xG-margin model against;
  this build has no event-level data source (docs/DECISIONS.md already covers why).
  Shipping a v2 trained only against this build's own Monte Carlo simulator's output
  would be circular, not a real backtest, so it wasn't done.
- No deployment: `docker-compose.prod.yml` and all three GitHub Actions workflows
  are authored to the same stack docs/DESIGN.md names, but none have been run, per
  the explicit "don't deploy it yet" instruction this phase was built under.

Verified: `python -m evals.run_all` run for real against this build's seeded
`dev.db` — 10/10 samples, 100% numeric-validator pass rate on both coach and match
reports, 0 fallback triggers. `tests/test_evals.py` (3 tests) covers both runners
mechanically, including the "no golden set / no embedder" degraded paths.

## Phase 8 — Real data integration

Replaced the synthetic Transfermarkt/Understat stand-in with the real, public
dcaribou/transfermarkt-datasets export (CC0; `pipeline/download_real_data.py` fetches
it). Built `pipeline/real_source.py`, matching `synthetic_source.generate()`'s exact
`SyntheticWorld` shape, and `pipeline/data_source.py` as the single swap point
(`DATA_SOURCE=real` env var) — `pipeline/ingest.py` and `pipeline/pricing.py` now
import through it instead of `synthetic_source` directly, exactly the one-call-site
promise `docs/DECISIONS.md` made when the synthetic generator was built.

What's genuinely real now: player identity, nationality, position, age, current club,
and **market value** (50k+ real players); real WC2026 squads (derived from actual
June 2026 match lineups, not the dataset's own sparse `current_national_team_id`
field); real 2025/26 UCL club rosters; real minutes/goals/assists/cards (aggregated
from `appearances.csv` over a ~14-month window). Not real: there is no shot-quality or
event-level data source in this export, so xG/xA are approximated as goals/assists,
and the remaining advanced per-90s (tackles, aerials, progressive carries, etc.) are
synthesized from each player's real market-value percentile within their position
group — a real signal driving the same noise-added technique `synthetic_source.py`
uses, not fabricated from nothing. This is stated plainly in `real_source.py`'s
docstring so it's never mistaken for real StatsBomb-grade data.

**Three real data-quality bugs found and fixed, each caught by checking actual
numbers rather than trusting the first pass** (the same discipline as the Phase 1
WC-squad-field finding):
1. First version force-assigned any candidate player whose real club wasn't one of
   the 36 UCL 2025/26 clubs to an arbitrary UCL club (to satisfy `ingest.py`'s
   `club_by_id[tm.club_id]` lookup, which requires every player's club to exist in
   `world.clubs`). Caught before it ran — fixed by building `clubs` from every club a
   selected player is *actually* at (big-5-but-non-UCL clubs included), not just the
   UCL 36.
2. With that fixed, several real WC2026 squads still came back at 6-9 players instead
   of ~26 (South Africa, Qatar, Egypt, Iran, Iraq, Jordan, Uzbekistan, Panama) —
   their domestic leagues aren't in this dataset's `clubs.csv`/`competitions.csv`
   coverage (mostly European + a handful of others), so those players' `current_club_id`
   pointed at clubs with no metadata row at all. Fixed by giving such players a
   minimal real-data placeholder club (name from `players.csv`'s own
   `current_club_name` column, country honestly marked "Unknown (league not in
   dataset)") instead of silently dropping real WC2026 squad members.
3. 3 of the 36 real UCL clubs (smaller-league debutants, e.g. first-time European-cup
   sides) were still thin (1-9 players) via `current_club_id` alone, because
   `players.csv` itself has incomplete profiles for them. Fixed the same way the
   WC2026 squads were fixed in Phase 1 — derive squad membership from real 2025/26
   UCL match lineups (`game_lineups.csv`) too, unioned with the `current_club_id`
   path. Final squads: 43/48 WC2026 teams at 24-26 real players each (5 teams dropped
   entirely — their ids never appear in `national_teams.csv`, so no display name
   exists for them; honest to drop rather than guess one), all 36 UCL clubs at
   15-50 real players each.

`db/models.py`: widened `Player.nationality` / `Club.country` / `NationalTeam.country`
from `String(3)` (ISO codes, synthetic-only) to `String(64)` to hold real full country
names ("Democratic Republic of the Congo"). `pipeline/ingest.py`'s
`TOP_LEAGUE_COUNTRIES` now covers both the synthetic ISO codes and the real dataset's
full country names for the big five leagues, since `club["country"]` can be either
depending on `DATA_SOURCE`.

Verified end-to-end against a fresh SQLite db (`DATA_SOURCE=real python -m
pipeline.run_all`, seed 42): 4,755 players, 490 clubs, 43 national teams, 2,466 squad
rows, 3,842/3,842 matched by `id_resolution` (0 unresolved — expected, since there's
only one real source feeding both the "TM" and "Understat" sides here, so every match
is `dob_club_exact`/`dob_club_fuzzy` at score 1.0, not the deliberate-disagreement
case Phase 1's synthetic two-source setup exercises), pricing MAE ~€3.33M (40.7% of
mean real market value — in line with the synthetic baseline's ~40.4%, so the
pricing model generalizes rather than overfitting the synthetic distribution),
ability scores spanning 4.1-96.5 (mean 49.6 — not collapsed to a constant, the
Phase 2 bug class this build is specifically alert to). `ruff check .` and `mypy
engine rag llm pipeline db config api evals` both clean. Full `pytest` suite (69
tests, all written against the default synthetic path) still passes unchanged.

**Manual browser playthrough against the real data** (`cp dev_real.db dev.db`, real
`uvicorn`/`npm run dev`): drew a real opponent (Ecuador); scouting report correctly
surfaced real current Ecuador internationals as danger players (Willian Pacho, Piero
Hincapié, Moisés Caicedo — real positions, sane non-collapsed ability scores);
built an 11-player XI from real, currently-active elite players (Dembélé, Wirtz,
Yamal, Donnarumma, Saliba, ...) at real transfermarkt-derived prices, €91M under
budget; Coach's Report returned a 95.1/100 rating, a 54.2%/22.4%/23.4% simulated
win/draw/loss split, and correctly flagged genuinely out-of-position picks (a CB
played at LB) with real, priced, budget-legal swap suggestions (real alternative
players, not placeholders). Confirms the full stack — pipeline, engine, API, frontend
— works end-to-end on real data, not just that the ingest step runs.

**Still not done, same as Phase 7, unchanged by this phase**: the two human-written
golden eval sets (explicit user instruction: leave them for a human to write) and any
deployment (explicit user instruction: don't deploy yet). Rating v2 is also still not
attempted — real match results (`games.csv`) now exist and would support a genuine
backtest, but building a trained model for it is further work than "integrate real
data" covers and wasn't requested.

## Phase 6c — rating rebalance + screen-by-screen gap closure (in progress)

**Step 0** (rating diagnosis) and its approved fix: see `docs/DECISIONS.md`
"Rating/simulation rebalance." Budget raised €500M -> €1B: see `docs/DECISIONS.md`
"Budget raised."

**Batch A — done, tested, Playwright-checked** (`frontend/e2e/batch-a.spec.ts`):
- A1 opponent "where they're weak" (screen 3): `engine/team_profile.py::opponent_weak_zone`,
  wired into `/sessions/{id}/scout`'s new `weak_zone` field, rendered in `Scouting.tsx`.
  `tests/test_team_profile.py` (5 tests).
- A2 strengths (screen 5): `engine/strengths.py` mirrors `weaknesses.py` (zone
  advantage, matchup win, role coverage), top 3 by severity, added to
  `LineupAnalysis.strengths`, rendered in `CoachReport.tsx`. `tests/test_strengths.py`
  (5 tests).
- A3 man of the match (screen 8): `engine/motm.py`, using real per-event scorer/assist
  credit (now tagged on `MatchEvent`) plus a defensive-contribution score (expected
  vs actual goals conceded per zone, reusing the same zone data
  `chance_share_by_zone` already carried). Always produces a winner (0-0 ties broken
  by ability score). Wired through `graph/nodes.py`'s `simulate` node into
  `/decision` and `/simulate`, rendered in `MatchReport.tsx`. `tests/test_motm.py`
  (5 tests).
- A4 play again (screen 8): `POST /sessions/{id}/rematch` pins the new session to
  the same opponent (`graph/nodes.py::draw` now accepts `fixed_opponent_team_id`),
  carries over formation/lineup, re-validates rather than assuming still legal.
  `BuildXI.tsx` accepts prefill props. 2 new cases in `tests/test_api.py`.

**Batch B — in progress**:
- B1 opponent lineup (screen 3): done. Scouting's "Likely Lineup" now reads the
  SAME `opponent_lineup_assignments`/`opponent_formation` state keys
  `engine.rating`/`engine.counter`/`engine.simulation` already use (verified, not
  assumed — `graph/nodes.py`'s `draw()`/`opponent_counter()` are the only writers;
  `scout()` was only ever missing a read of them, there was no second,
  divergent computation to unify). Labelled `lineup_source: "estimated"` (a squad's
  best-XI-by-ability, not real match-lineup-frequency data — see below). Verified
  with a real counter round in `tests/test_api.py` and
  `frontend/e2e/batch-b.spec.ts`.
  **Incidental finding, not a regression**: some synthetic squads are too thin in
  one position group for `draw()`'s greedy fill to reach all 11 slots (a
  pre-existing gap in that function, invisible until this phase exposed the
  lineup in the UI for the first time). Not fixed in this phase — tracked here so
  it isn't lost.
  **Not implemented, scoped out, reason**: the spec's literal "most frequent
  starters from real recent Transfermarkt lineups" requires persisting
  per-team starting-XI frequency from `game_lineups.csv.gz` into the production
  schema (currently only used transiently during real-data ingestion, then
  discarded) plus a full real-data pipeline re-run (~10 minutes) to test. Given
  Batch B's framing as "polish," this was deferred rather than rushed; the
  honestly-labelled "estimated" fallback is what's shipped.
- B2 what worked / what didn't (screen 8): done. `engine/postmatch.py` compares
  each pre-match def-zone weakness/strength against this match's actual
  zone-tagged conceded goals vs the pre-match expected share
  (`POSTMATCH_EXPOSURE_MARGIN_GOALS` in config). Non-def-zone items (press
  resistance, out-of-position, etc.) are honestly marked `inconclusive` rather
  than fabricating a zone-level claim the engine can't actually measure. Wired
  into the `simulate` graph node, `SimulateResponse`/`DecisionResponse`, and
  rendered as a "What Worked / What Didn't" card on `MatchReport.tsx`.
  `tests/test_postmatch.py` (5 tests) + `frontend/e2e/batch-b.spec.ts`.
- B3 animations (screens 2 and 7): done. Pure-CSS entrance animations
  (`.reveal-pop`, `.fade-in-up` in `theme.css`) for the opponent reveal on the
  draw screen and each match-day timeline event. The timeline's reveal timing
  itself (one event every 450ms) is driven in `MatchDay.tsx`'s own state, not
  CSS alone, specifically so the required Skip control has something real to
  skip — clicking it clears the timer and shows every event immediately.
  `prefers-reduced-motion` is checked both in CSS (disables the animations) and
  in JS (skips the staged timing entirely, showing all events on mount).
  Verified with two Playwright cases: the skip control actually works, and
  reduced-motion mode shows everything immediately with no skip control
  rendered at all (nothing to skip).
- B4 share (screen 8): done, frontend-only, no backend/persistence.
  `frontend/src/shareCard.ts` builds the plain-text summary ("Copy Result",
  via `navigator.clipboard.writeText`) and draws the downloadable result image
  (scoreline, opponent, rating, Man of the Match, manager score) onto a hidden
  `<canvas>`, exported as a PNG download. Verified with a real clipboard
  read-back and a real captured download event in
  `frontend/e2e/batch-b.spec.ts`, not just that the buttons render.

Batch A and B are both now complete. Final suite: 97 backend tests passed,
`ruff check .` and `mypy engine rag llm pipeline db config api evals graph` both
clean, frontend `tsc --noEmit` clean, 6 Playwright tests passed covering every
new UI element in both batches.

## v1 completion — GitHub publish

Published to https://github.com/Rithvik-Ambati/galacticos-on-a-budget. Secret scan
(full history + working tree) clean before the first push; no files over 10MB
anywhere in history. Branch renamed `master` -> `main`. `.gitignore` hardened,
`.env.example` completed, Makefile's `typecheck`/`lint` targets fixed to match what
was actually being run all along (see `docs/DECISIONS.md` for why `ruff format
--check .` was dropped rather than reformatting 45 of 92 files as a surprise).

**Rating work (candidate C + coherence check)**: confirmed already committed and
complete from the prior session, with evidence that it was run on real opponents
throughout (every diagnostic script explicitly set `DATA_SOURCE=real` before
ingesting, never relying on a default) — no re-run needed. Full numbers in
`docs/DECISIONS.md` "Rating/simulation rebalance, pass 2."

### Part 2a — synthetic squads audit and the "no silent fake data" guard

Audited every code path that could put a synthetic player in front of a real
player: only `pipeline/data_source.py`'s default was the problem (it silently fell
back to the fictional generator), not `engine/demo_fixtures.py` (confirmed
genuinely test/demo-only — never imported by `graph/`, `api/`, or
`pipeline/ingest.py`). Reported this before changing anything, per instruction;
approved fix (option 1 + guards) implemented:

- `DATA_SOURCE` now defaults to `"real"`; `DATA_SOURCE=synthetic` is an explicit
  opt-in.
- New `ingest_metadata` table (migration `0002_ingest_metadata`): every
  `pipeline.run_all` run records its data source, the real dataset's snapshot date
  (when applicable), and a run timestamp.
- `api/main.py`'s `lifespan` refuses to start the API at all if that table is
  empty (`NotIngestedError`, with a clear message), and otherwise exposes the
  latest row's `data_source` on `/health` and `app.state`.
- The frontend shows a persistent "DEMO DATA — fictional players, not a real
  opponent" banner on every screen whenever `/health` reports `"synthetic"`.
- Every test module that calls `run_ingest` (`test_api.py`, `test_evals.py`,
  `test_graph.py`, `test_rag.py`) now sets `DATA_SOURCE=synthetic` explicitly, and
  so do `ci.yml`/`nightly-eval.yml`; `weekly-pipeline.yml` deliberately leaves it
  unset (production refresh should be real) and now downloads the dataset first.
- README's primary setup path is now the real-data one; synthetic is documented as
  the dev/test option.

**Tests**: `tests/test_lifespan.py` (4 new — metadata-lookup helper directly, and
`lifespan()` end-to-end against an isolated engine, both for the empty-table and
present-metadata cases) + `frontend/e2e/data-source.spec.ts` (a real re-seed with
`DATA_SOURCE=synthetic` confirms the banner actually renders, not just that the
component code exists). Full suite: 101 backend tests, ruff/mypy clean, 7
Playwright tests.

### Part 2b — thin squads always field exactly 11

`engine/opponent_lineup.py::build_opponent_lineup` (full detail in
`docs/DECISIONS.md` "Thin squads always field exactly 11, with fallback tracked
and shown"). Fills thin position groups from the nearest adjacent group, tracks
every out-of-position fill, and the scouting report shows them. `graph/nodes.py`'s
`draw()` excludes (and logs) any squad that can't field 11 even with fallback.

**A real bug found and fixed along the way, not introduced by this change**:
`draw()`'s UCL candidate query selected every row in the `clubs` table (~490 —
every club any real player happens to play for) instead of the 36 clubs that
actually have a squad, giving roughly a 93% chance of drawing a 0-player opponent
in UCL mode. Fixed by querying `Squad.team_id` (filtered by `tournament`) directly.

**Audit, real data, both modes**:

| Mode | Fieldable (of real candidates) | Excluded | Needed >=1 fallback fill | Total fills |
|---|---|---|---|---|
| WC2026 (national teams) | 43 / 43 | 0 | 3 | 4 |
| UCL2025-26 (clubs) | 36 / 36 | 0 | 2 | 2 |

(5 of the 48 real WC2026 teams and ~454 of the ~490 clubs `real_source.py`
references have no squad at all in this dataset — never real candidates, not a
Part 2b exclusion; see Phase 8/6c Part 2a.)

**Tests**: `tests/test_opponent_lineup.py` — 3 unit tests (fallback chain fires,
no fallback needed when a squad has full depth, returns `None` when genuinely too
thin) plus the requested property test: for every team in both modes the
synthetic seed makes fieldable, the built XI has exactly the 11 formation slots,
all distinct real squad members. 105 backend tests passing, ruff/mypy clean.
No dedicated Playwright check was added for the (rare -- 3/43, 2/36) scouting-page
out-of-position banner specifically; the existing Batch A/B Playwright suite
already exercises `draw()`/Scouting repeatedly and would catch a crash, but
doesn't force the banner's specific content to appear.

### Part 2c — real opponent lineups from real match-start frequency

Full detail in `docs/DECISIONS.md` "Real opponent lineups from real match
frequency". `pipeline/real_source.py` now counts real starting-lineup appearances
per candidate per position from `game_lineups.csv.gz`, persisted into a new
`team_lineup_frequency` table (migration `0003_team_lineup_frequency`).
`engine/opponent_lineup.py::build_opponent_lineup` ranks candidates within each
Part 2b fallback tier by that start count first, role-fit as the tiebreak --
"most frequent starters," not "most able players." `graph/nodes.py::draw()`
labels the opponent XI `lineup_source="real"` once at least
`config.game.MIN_REAL_LINEUP_SLOTS` (7/11) slots were won by real starts, else
`"estimated"`; `api/routers.py::scout()` now returns this computed value instead
of the hardcoded placeholder it shipped with in Part 2b. Same XI object the
rating/counter/simulation engines already consume -- no second lineup computed
anywhere.

**Audit, real data, both modes** (re-ran `pipeline.run_all` with `DATA_SOURCE=real`):

| Mode | Fieldable | `"real"` | `"estimated"` |
|---|---|---|---|
| WC2026 (national teams) | 43 | 37 | 6 |
| UCL2025-26 (clubs) | 36 | 35 | 1 |

**Tests**: 6 new cases in `tests/test_opponent_lineup.py` -- frequency outranks
ability within a tier, `real_fill_count` zero with no frequency data, it only
counts slots actually won by frequency, `load_lineup_frequency`'s per-team lookup
(including the unknown-team empty case), and a sanity check on
`MIN_REAL_LINEUP_SLOTS`. Full backend suite: 110 passing, ruff/mypy clean. Re-ran
the existing B1 Playwright check (`frontend/e2e/batch-b.spec.ts`) against the same
real-seeded DB used for the audit above -- still passes, alongside the rest of
the Batch A/B suite (6/6).

**Environment note**: this session's Windows temp drive (`C:`) was at 0 bytes
free, which made SQLite-backed tests fail with "database or disk is full" when
pytest's `tmp_path` fixture defaulted there. Worked around with
`pytest --basetemp=<path on D:>` (not a code change, not committed -- `.pytest_tmp/`
added to `.gitignore` in case it's reused). `frontend/e2e/playwright.config.ts`'s
`baseURL` is `http://127.0.0.1:5173`; this machine's `vite` default bind resolved
to `::1` (IPv6) only, which the Playwright run connects to over IPv4 and failed
against with `ERR_CONNECTION_REFUSED` -- resolved locally by starting vite with
`--host 127.0.0.1`. Neither is a repository bug; noted here only because the next
session hitting the same local Playwright run will see the same symptom.

## Part 3 -- evaluation suite

Most of the scaffolding (`evals/numeric_eval.py`, `evals/retrieval_eval.py`,
`evals/run_all.py`, `evals/golden/`) already existed from an earlier session;
this pass filled the remaining gaps against the spec and fixed what it found.

- **Golden set templates renamed and filled with 2 example rows each**:
  `evals/golden/retrieval_queries.jsonl` and `evals/golden/chat_questions.jsonl`
  (previously `retrieval.jsonl`/`chat.jsonl`, both genuinely empty). Each example
  row carries `"is_example": true`; every runner that reads these files filters
  that field out before scoring, so a file with only example rows is still
  treated as an empty golden set (`evals/golden/README.md`). CLAUDE.md's "golden
  sets are human-written, never generate or edit expected answers" is unaffected
  -- these are illustrative schema rows, not judged answers, and are never scored.
- **`evals/retrieval_eval.py`**: added `render_ablation_table()` -- the markdown
  Recall@10/MRR/nDCG@10 table (best nDCG@10 bolded) that `run_all.py`'s console
  output and this doc's evaluation-results section both link to, plus a
  `__main__` entrypoint so `make eval-retrieval` runs it standalone.
- **`evals/embedding_benchmark.py`** (new): the same three metrics plus p50/p95
  query-embedding latency, for BAAI/bge-small-en-v1.5 (the production default),
  BAAI/bge-base-en-v1.5 and intfloat/e5-base-v2 -- the exact comparison
  `rag/embeddings.py`'s own docstring cites as the reason bge-small was chosen.
  Corpus and queries are batch-encoded in memory for the comparison only; nothing
  is ever written to `documents.embedding` (production stays on whatever the
  real ingestion pipeline set). Skips cleanly with an empty golden set, same as
  every other runner.
- **`evals/faithfulness_eval.py`** (new): RAGAS's `Faithfulness` metric over the
  same coach/match report samples `numeric_eval.py` uses (factored out into new
  `evals/_report_samples.py` so the two evals can't drift on how a sample is
  built). Under `StubProvider` this reports 1.0 by construction with no RAGAS/LLM
  call at all (`StubProvider.complete` is the identity function, so the
  "restyled" text IS the engine-grounded template verbatim) -- no network, no
  cost, nothing for CI to accidentally run live. Under a live Anthropic provider
  it actually invokes RAGAS, judged by that same provider, via a small
  `BaseRagasLLM` wrapper (`_build_ragas_llm`) that avoids needing
  `langchain-anthropic` as a dependency.
  **Known environment limitation**: `ragas` could not be installed in this
  session -- one of its own hard (non-optional) dependencies, `scikit-network`,
  ships no prebuilt wheel for any platform and needs a C++ build toolchain
  (Microsoft Visual C++ Build Tools) to compile from source, which this machine
  doesn't have and which installing is outside this task's scope. The live-
  provider code path is written against RAGAS 0.4.3's documented API (inspected
  directly from the downloaded wheel) but could not be executed end-to-end here.
  The `StubProvider` path (the one CI and `make eval` actually exercise) was
  fully run and is unit-tested.
- **`evals/numeric_eval.py`**: enhanced with a DeepEval custom metric
  (`NumericFaithfulnessMetric`, `deepeval` installed cleanly, no build-toolchain
  issue) wrapping `llm/validator.py::validate_numbers` -- deterministic, no LLM
  judge, usable with DeepEval's own `assert_test`/`evaluate` tooling. Reports two
  new fields, `deepeval_coach_score`/`deepeval_match_score`: an independent
  re-check of the FINAL shown text (after any regenerate-then-fallback), expected
  to always be 1.0, proving the fallback safety net holds even when the LLM's own
  first/second attempt needed discarding. Also fixed the same "selects every
  `Club`/`NationalTeam` row instead of just the ones with a real `Squad`" bug
  Part 2b found in `draw()` -- this eval had the identical pre-existing bug,
  which only surfaced once run against the full real dataset instead of the
  smaller synthetic one.
- **`evals/live_llm_test.py`** (new): refuses to do anything unless
  `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` are both set (never logs the
  key itself, only checks its presence); builds one real lineup and narrates both
  reports through the live model, re-checked by the same numeric validator
  production uses. Not run in this session, per instruction -- built so the
  project owner can run it by hand.
- **Makefile**: `eval-retrieval`, `eval-embeddings`, `eval-faithfulness`,
  `eval-numeric`, `eval-live` (each script standalone) and `eval` (numeric +
  retrieval + faithfulness via `run_all.py`, plus the embedding benchmark --
  everything except `eval-live`, which nothing else depends on).
- **Fixed a baseline/regression-gate bug found while verifying this**:
  `evals/run_all.py` wrote its baseline to `evals/reports/baseline.json`, but
  `.gitignore` ignores everything under `evals/reports/` -- so the CI regression
  gate Part 4 needs ("fail if Recall@10 drops >2 points vs baseline") had nothing
  committed to compare against on a fresh checkout, and the drop check itself was
  never actually implemented (the threshold constant existed but nothing read
  it). Moved the baseline to `evals/baselines/baseline.json` (tracked, per the
  original spec), and `run_all.py` now reads the previously committed baseline's
  Recall@10 for the winning method and fails if it dropped more than
  `RECALL_DROP_THRESHOLD` before overwriting it with the new run's numbers.

**Verification**: full backend suite 119 passing, ruff/mypy clean. Ran
`python -m evals.run_all` end-to-end against the real-seeded DB from Part 2c --
numeric eval 1.0/1.0 (both pass rate and DeepEval score), faithfulness 1.0/1.0
(stub-by-construction), retrieval skipped cleanly (golden set still has only its
2 example rows -- filling it with real queries is on the project owner, per
CLAUDE.md). `evals/baselines/baseline.json` written. Smoke-tested
`embedding_benchmark.py` directly against the real document corpus with a
synthetic one-query golden set (not committed) to confirm the batched-encoding
path actually ranks correctly end-to-end before relying on it.

## Part 4 -- CI

- **`.github/workflows/ci.yml`**: added an `e2e` job (new) that seeds a synthetic
  SQLite DB, starts the FastAPI backend and the Vite dev server (not `vite
  preview` -- `vite.config.ts`'s `/api` proxy is only defined under `server`, not
  `preview`), waits on both with a plain `curl` retry loop (no new npm
  dependency), and runs the full Playwright suite against them. The existing
  `backend` job's eval step already fails the build on a numeric-validation drop
  or a Recall@10 regression -- both are `evals/run_all.py`'s own exit code, not
  separate CI logic. Fixed the artifact-upload path left over from Part 3's
  `evals/reports/` -> `evals/baselines/` move. No job needs a secret: every job
  sets `LLM_PROVIDER=stub` and `DATA_SOURCE=synthetic` explicitly.
- **`.github/workflows/nightly-eval.yml`**: added the embedding-model benchmark
  (not run on every PR, only nightly) and a faithfulness gate step
  (`evals/check_faithfulness_gate.py`) that activates only once a human has
  committed `evals/baselines/live_faithfulness_baseline.json` by running
  `evals/faithfulness_eval.py` with `LLM_PROVIDER=anthropic` set (that script's
  `__main__` block writes the file automatically whenever it runs live). With no
  such file committed yet, the gate passes trivially and says so.
- **Verification**: pushed to `main` and watched the run (`gh run watch`,
  reported in the final summary) -- fixed whatever came back red, re-pushed,
  confirmed all jobs green before moving to Part 5.

### How to demonstrate a failing gate, on a throwaway branch

None of these should be pushed to `main` -- make the change on a scratch branch,
push it, watch the job go red in the Actions tab, then delete the branch.

**Numeric-validation failure** -- force the validator to reject text it would
normally accept, by tightening its tolerance in `llm/validator.py::_matches` to
exact match:
```python
tolerance = 0.0  # was: max(0.5, abs(a) * 0.01)
```
`evals/numeric_eval.py`'s coach/match reports round some values for display
(e.g. `{value:.1f}`), which the normal 1%-relative tolerance absorbs but an exact
match won't -- `evals.run_all` reports `coach_report_pass_rate < 1.0` and exits 1.

**Recall@10 regression** -- fill `evals/golden/retrieval_queries.jsonl` with a
couple of real queries, run `make eval` once locally to get a real baseline
committed, then edit the committed `evals/baselines/baseline.json` by hand and
inflate the recorded `recall_at_10` for the current best method by more than
0.02 above what the next run will actually produce. The next `python -m
evals.run_all` (locally or in CI) prints `Recall@10 regression: ... -> ...` and
exits 1.

**Faithfulness gate** -- commit a throwaway
`evals/baselines/live_faithfulness_baseline.json` with a score below 0.90:
```json
{"coach_faithfulness": 0.5, "match_faithfulness": 0.5, "n_samples": 1}
```
`python -m evals.check_faithfulness_gate` (and the nightly workflow) then prints
`FAIL: faithfulness 0.5 is below the 0.9 gate.` and exits 1.

## Part 5 -- observability

**Starting state**: `config/settings.py` had Langfuse connection settings
(`langfuse_public_key`/`langfuse_secret_key`/`langfuse_host`) but nothing in the
codebase actually imported `langfuse` or created a single trace -- no gaps to
"fill," the whole integration needed building.

**What was built**: `observability.py` (new, top-level -- not inside `engine/`,
`llm/`, or `rag/`, since CLAUDE.md's module boundaries forbid `engine/`
importing `llm/`/`api/`/`db/`, and this needs to be callable from
`graph/nodes.py`'s engine-call sites as well as `rag/`/`llm/`). Two primitives:
`traced_span` (a context manager, no-op yielding `None` unless
`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are set) and `traced_node` (a
decorator for `graph/nodes.py`'s `GameState -> dict` node functions, tagging
the whole call with `state["session_id"]`).

Instrumented:
- **Every node** in `graph/nodes.py` (`draw`, `validate`, `analyse`,
  `narrate_report`, `opponent_counter`, `simulate`, `narrate_match`, and the
  post-interrupt half of `chat`) via `@traced_node` -- covers "engine
  analyse/counter/simulate spans tagged with session_id" directly, since those
  are node functions, plus every other node as a side effect. `build` and
  `user_decision` are skipped deliberately: they're pure `interrupt()` calls
  with no work before pausing, and wrapping them would double-trace (LangGraph
  re-executes a node from the top on resume, so a span opened before
  `interrupt()` would appear to "complete" when the graph merely paused).
- **Every real LLM call**: `llm/narrator.py::_traced_complete` wraps both
  `provider.complete()` call sites (first attempt and the regenerate retry) as
  a `generation` span, nested under whichever node's trace is active --
  Langfuse's OTEL-based session propagation means `session_id` only needs
  setting once, at the node level, not repeated on every nested span.
- **Retrieval**: `rag/retriever.py::retrieve`/`retrieve_ablation` (renamed the
  originals to `_retrieve_impl`/`_retrieve_ablation_impl` and added thin traced
  public wrappers, to avoid re-indenting either function's existing
  retry/fallback logic).
- **Rerank**: `rag/rerank.py::get_reranker`'s returned closure -- the single
  choke point every rerank call in the codebase already goes through.
- **SQL tool**: `llm/sql_tool.py::execute_guarded_sql` (same rename+wrapper
  pattern as retrieval).
- **Eval scores attached to traces**: `evals/_report_samples.py` now opens one
  `eval.sample` trace per generated sample (both `narrate_coach_report`/
  `narrate_match_report` calls nest under it) and hands back its `trace_id`.
  `evals/numeric_eval.py` and `evals/faithfulness_eval.py` call the new
  `observability.attach_score(trace_id, name, value)` after scoring each
  sample, recording `numeric_faithfulness_*`/`ragas_faithfulness_*` directly
  against that trace.
- **README**: new "Observability" section -- how to point `.env` at a Langfuse
  instance and what you'll see once you do.

**Tests**: `tests/test_observability.py` (new, 10 cases) against a fake
Langfuse client (no real server/keys in this environment) -- confirms both the
no-op path (nothing configured) and that a configured client receives the
right `start_as_current_observation`/`update`/`create_score` calls, including
session_id tagging and trace-id capture. `tests/test_graph.py` gained
`test_full_session_runs_with_tracing_configured`: the same full draw -> build
-> analyse -> lock_in -> simulate flow as the existing end-to-end test, but
with a fake client active, asserting every `node.*` span in that flow actually
carries `session_id`. Full backend suite: 134 passing, ruff/mypy clean (added
`observability.py` to both the Makefile's and `ci.yml`'s typecheck targets).

**Not done**: real end-to-end verification against an actual running Langfuse
instance -- this environment has no Langfuse server and no keys, so everything
above is verified against a faithful fake of the SDK's documented interface
(`langfuse==4.16.0`'s own `Langfuse`/`LangfuseSpan` classes, inspected directly
via `inspect.signature`), not a live trace observed in a real Langfuse UI. The
project owner should sanity-check one real session against a local
`docker compose up -d` Langfuse instance before relying on this.
