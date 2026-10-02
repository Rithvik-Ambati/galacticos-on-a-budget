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
