# Decisions

Format: what, why, where it lives.

## Rating/simulation rebalance (Phase 6c, Step 0)

**What**: `engine/simulation.py::expected_goals`'s coefficients — now named constants
in `config/game.py` (`EXPECTED_GOALS_*`) instead of inline magic numbers, per
CLAUDE.md's "no magic numbers in engine logic" rule, since this was the moment they
needed tuning anyway. `EXPECTED_GOALS_DEFENCE_SUPPRESSION_WEIGHT` raised 0.6 -> 1.0
and `EXPECTED_GOALS_OPP_MATCHUP_SUPPRESSION_WEIGHT` raised 0.3 -> 0.6.
`EXPECTED_GOALS_OPP_ATTACK_PROXY_WEIGHT` (1.6) deliberately left unchanged.

**Why**: user-reported symptom — a 95.1-rated lineup only won 54.2% vs a real
opponent. Measured, not assumed: ran 54 varied lineups (3 spend levels x 3 real
opponents of deliberately different strength) through rating + simulation. Found two
compounding causes: (1) ratings compress into an 87-92 band for *any* genuinely good
lineup, since sub-ratings are position-relative ability *percentiles* and there's
only so much percentile room above "already selecting the best available players";
(2) `opp_attack_proxy` (the opponent's own danger-player ability, itself often 85-95
for a real elite team) was weighted 1.6 in `lam_opp`, while the user's own
defence/matchup suppression of that same term was only weighted 0.6/0.3 — so even a
maxed-out defence barely dented a strong opponent's expected goals. The single
highest-rated sampled lineup against the strongest test opponent (92.5 overall,
defence 90.9, matchup 95.3) still only won 53.3%.

**Fix chosen over the alternative**: raising the suppression weights (scoped to
`expected_goals` alone) rather than reworking the rating formula itself, which
`engine/weaknesses.py`, `engine/swaps.py`, `engine/optimizer.py::manager_score`, and
every narrator template depend on — much larger blast radius for the same underlying
problem. Rating compression (cause 1) was deliberately left alone as a secondary,
lower-risk finding, not fixed in this change.

**Measured effect (same 54 lineups, before vs after)**: median win% vs the weakest
opponent 63.5% -> 71.2%; vs the mid opponent 53.0% -> 59.9%; vs the strongest
opponent 49.7% -> 56.6%. The concrete problem is gone — every sampled lineup now
wins more than it loses against all three opponents, where several previously had a
losing record (<50% win) against the strongest one. The shift is a fairly uniform
+7 points across all three opponent strengths rather than a sharper
stronger-for-weak-opponents/milder-for-strong-opponents curve — a conservative first
pass, not refuted as insufficient, but flagged in case a sharper "a high rating
should feel dominant" effect is wanted later (the same named constants are the next
turn to reach for, no code structure change needed).

**Tests**: `tests/test_simulation.py` — a hand-computed regression pin for
`expected_goals` at these coefficients, two monotonicity properties (higher
defence/matchup strictly suppresses the opponent's lambda), a regression lock on the
exact diagnosed scenario (lam_user/lam_opp ratio now > 1.8, was ~1.48), and a
clamping check at the extremes.

## Rating/simulation rebalance, pass 2

**What**: further raised `EXPECTED_GOALS_ATTACK_WEIGHT` 1.6 -> 2.0 and
`EXPECTED_GOALS_USER_MATCHUP_WEIGHT` 0.6 -> 1.0 (pass 1's values). Opponent
suppression weights (from pass 1) left untouched.

**Why**: pass 1 was validated against the Step 0 54-lineup sample, which turned out
to only span a narrow ~5-rating-point band (all budget-varied, near-top-ability
picks) — useless for testing "does a dominant lineup feel dominant." Measured
against the TRUE optimal lineup (`engine.optimizer.find_optimal_lineup`, not a
heuristic) and a deliberately worst-case lineup per opponent: the optimal lineup
only reached 66.6% win vs a weak opponent and 53.1% vs a strong one, short of
user-set targets (75-85% / 55-65%). Pass 2's change is scoped to the attack side of
`lam_user` only (not opponent suppression), so it wouldn't re-risk the
weakest-vs-strongest gap and monotonicity properties, which were confirmed healthy
(20+ point gaps, r>0.99 rating-win correlation) once tested against this wider,
worst-to-optimal range rather than the narrow Step 0 sample.

**Measured effect (real optimal/worst lineups, live coefficients)**: optimal vs
Iran (weak) 66.6% -> 76.3% (target 75-85%, met); optimal vs Türkiye (strong)
53.1% -> 63.3% (target 55-65%, met, close to the upper bound). Draw% stayed in a
sane 16.8-24.9% range throughout.

**Coherence check, requested alongside this change**: re-ran the 54-lineup
comparison with common random numbers (same seed for every lineup, not a fresh one
each time) at 50,000 runs. Non-monotonic rating-vs-win% steps did **not**
disappear (5-7 out of 17 per opponent, same order of magnitude as before) — so it
isn't Monte Carlo noise. Root cause, confirmed: `expected_goals()` only reads
`attack`/`defence`/`matchup` from `RatingResult.sub_ratings`; `RATING_WEIGHTS`
gives those three a combined 64% of overall rating, leaving `midfield_control`
(18%), `cohesion` (10%) and `balance` (8%) — 36% of the displayed number — with
zero influence on simulated win%. Two lineups can share an overall rating through
different mixes of these six components while only the attack/defence/matchup mix
actually drives the match outcome.

**Practical impact, tested rather than assumed**: ran the real swap optimizer
(`engine/swaps.py`, which ranks candidates by overall-rating gain) on 20 realistic
lineups and compared simulated win% before/after each top-ranked suggested swap
(common random numbers per pair). **0/20** cases raised rating while lowering
win% — every suggested swap improved both. Read: swap candidates are ranked among
same-position options sorted by ability, and ability_score drives
attack/defence/matchup and midfield_control/cohesion/balance correlatively, so a
genuinely-better individual player tends to lift the win%-relevant components too,
even though the overall-rating ranking doesn't privilege them. Per the
user-specified threshold (propose a rating-architecture rework only if more than
1/20 swaps showed the rating-up/win%-down pattern), **no rework was proposed** —
the structural gap is real and now documented, but it isn't causing bad swap
advice in practice. Worth revisiting if a future, less ability-correlated swap
pool (e.g. role-fit-only re-ranking) ever makes the gap practically visible.

## Budget raised from €500M to €1B

**What**: `config/game.py::BUDGET_EUR` is now `1_000_000_000` (was `500_000_000`).
Updated everywhere that number was duplicated: `frontend/src/screens/BuildXI.tsx`'s
local fallback constant, `CLAUDE.md`'s one-line project summary, and
`docs/DESIGN.md` section 1's rules table.

**Why**: explicit user instruction.

**Effect, measured not assumed**: re-ran `pipeline.pricing`'s budget sanity check
against the synthetic world. At €500M, ~2 elite (top-2%-ability) players afforded
alongside 8 median starters; at €1B, ~5 do. A full top-2%-ability XI still does
**not** fit under €1B, so the budget still forces real trade-offs, just looser ones
than DESIGN.md section 1's original "~3 elite + 8 good" target — worth knowing if
a future session is asked to re-tune the pricing curve, since the curve itself
wasn't touched, only the budget it's measured against.

**A real bug this surfaced, unrelated to the budget itself**: doubling the budget
changed which lineup `engine.optimizer.manager_score` considers "best possible,"
which shifted a downstream narrated number (the manager-score percentage) just
enough to stop coincidentally landing within the validator's tolerance of the
literal `100` in "rates X/100 overall" — a number `llm/narrator.py`'s
`_coach_report_allowed_values` never explicitly whitelisted. It had been passing by
luck, not by correctness. Fixed by whitelisting `100.0` unconditionally (it's a
fixed template literal, never an engine fact that could be hallucinated). While
investigating, found a second, same-class pre-existing bug in the same function:
weakness evidence values that get printed as percentages (e.g.
`budget_misallocation`'s `{threat_share:.0%}`) were only ever whitelisted as their
raw fraction, never their ×100 display form — fixed the same way severity already
was. Both caught by `python -m pytest`, which is why "finish it" work always re-runs
the full suite after any change to a shared constant, not just the code that
constant obviously touches.
## Synthetic data instead of real Transfermarkt/Understat pulls

**What**: `pipeline/synthetic_source.py` generates ~830 players, 10 UCL club squads,
12 WC2026 national squads, and two independent "source" record sets (a canonical one
and a deliberately name-perturbed, partial-coverage one standing in for Understat),
all seeded from `config.settings.seed` so every run is reproducible.

**Why**: the Transfermarkt Datasets (dcaribou) are multi-GB and the real Understat
site has no bulk API — actually pulling either was out of scope for the time and
network budget available while building this. CLAUDE.md's workflow rule ("if the
spec is ambiguous or data does not match assumptions, stop and ask rather than
guessing") is exactly the instinct this follows: rather than silently fabricate a
single clean table that would make `pipeline/id_resolution.py` a no-op, the generator
produces two genuinely disagreeing sources so that module's actual matching logic
gets exercised and tested (`tests/test_pipeline.py::test_id_resolution_matches_
almost_everyone_correctly`). Every per-90 stat is generated with a real, tunable
correlation to a hidden `true_quality` value per player specifically so Phase 2's
ability scoring and pricing model have real signal to learn from — not noise that
happens to produce plausible-looking numbers.

**Swapping in the real thing later**: `pipeline/ingest.py` is the only module that
calls `pipeline.synthetic_source.generate()`; replacing it with real CSV loading
means rewriting that one call site, not the schema, id_resolution, features or
pricing modules, which all operate on the same `TmPlayer`/`UnderstatPlayer` shapes
regardless of where they came from.

**Update, Phase 8 — this promise was kept**: `pipeline/real_source.py` now loads the
real, public dcaribou/transfermarkt-datasets export and emits the exact same
`SyntheticWorld` shape; `pipeline/data_source.py` is the swap point
(`DATA_SOURCE=real`), and `pipeline/ingest.py`/`pipeline/pricing.py` import through it
instead of `synthetic_source` directly. One real consequence of there being a single
real source instead of two deliberately-disagreeing ones: `id_resolution.resolve()`
now matches ~100% of players at `dob_club_exact`/score 1.0 instead of exercising its
fuzzy path, since there's no second, independently-perturbed name source anymore —
expected, not a regression; the fuzzy-matching logic itself is still covered by
`tests/test_pipeline.py` against the synthetic two-source world, which is still the
default (`DATA_SOURCE` unset) and still what the test suite runs against. Full
findings and numbers: `docs/PROGRESS.md` Phase 8.

## SQLite fallback for the vector/relational store

**What**: `db/vector_type.py` stores embeddings as `vector(dim)` on Postgres and as a
JSON float array on every other SQLAlchemy dialect; `rag/dense.py` cosine-scans that
array in Python instead of using pgvector's HNSW operator when the dialect isn't
Postgres.

**Why**: Docker Desktop's engine would not start in this sandbox (no WSL2/Hyper-V
backend), so there was never a live Postgres to develop or test against. Rather than
leave the whole data/RAG layer unverified, every table and query path also works
against `sqlite+aiosqlite:///./dev.db` for local dev and the test suite.

**Where**: `db/vector_type.py`, `db/session.py`, `config/settings.py::database_url`.
Nothing about the Postgres path changed — `docker-compose.yml` and the Alembic
migration in `db/migrations/versions/0001_initial_schema.py` still create the
`vector` extension, the HNSW cosine index and the read-only role exactly as
DESIGN.md section 6 specifies. Switching `DATABASE_URL` to a real Postgres is the
only thing needed to use it; nothing in application code branches on which one is
active except the two files above.

## Zone-mismatch scoring uses a `duel_strength` stat, not raw ability

**What**: `engine/matchups.py` scores a defensive zone's strength using
`per90.get("duel_strength", ability_score)` — a specific recovery/duel stat when the
pipeline has computed one, falling back to the general ability score.

**Why**: DESIGN.md section 7.4 describes the zone-mismatch rule in terms of a specific
duel (opponent take-ons & progressive carries vs. defender tackles-won &
dribbled-past rate), not generic overall ability. Using ability_score alone made an
86-rated full-back with (deliberately, in the demo fixtures) weak recovery pace
score as "fine" against a fast winger, which doesn't match the rule as specified.
`rating.py`'s own sub-ratings (attack/midfield/defence) still use plain ability —
only the matchup-specific comparison in `matchups.py` uses the duel stat.

## Opponent zone threat mirrors sides, and blends in personnel

**What**: `engine/team_profile.py::zone_threat_map` mirrors `attack_channels` left/right
(an opponent's right winger threatens the user's *left* defensive zone, not their
right), and — when a specific opponent lineup is passed in (`engine/counter.py` always
passes one) — blends the static tactical baseline 50/50 with the ability of whoever
the opponent currently fields in that attacking flank.

**Why**: without the personnel blend, the opponent's "counter" moves (substitution,
reposition, formation change) couldn't change anything the rating model measures,
since v1's matchup score only read the opponent's static `TeamProfile`, not who's
actually on the pitch — which would make the whole counter mechanic cosmetic.

## v1 expected-goals formula is a placeholder for rating v2

**What**: `engine/simulation.py::expected_goals` derives Poisson lambdas from the
rating model's attack/defence/matchup sub-scores through a hand-tuned formula.

**Why**: DESIGN.md section 7.3 explicitly scopes a real xG-margin model (XGBoost on
historical matches) as Phase 7's rating v2, swapped in via the same `RatingModel`
interface only if it beats v1 on a backtest. There's no historical match dataset in
this build yet, so v1 fills the same slot with a transparent, documented approximation
rather than silently shipping a fake-precision number.

## LLM provider defaults to a deterministic stub

**What**: `llm/provider.py` ships a `StubProvider` that fills narration templates with
engine numbers and returns them verbatim — no network call, no API key. `LLM_PROVIDER`
in `.env` switches to a real Anthropic-backed provider once a key is supplied.

**Why**: No LLM API key is configured in this environment, and CLAUDE.md rule 1 (the
engine decides, the LLM only explains) means the stub is already a legitimate,
useful implementation of "narration" — it's deterministic and testable, and every
number it prints is still the engine's, satisfying `llm/validator.py` trivially. It
is not a mock standing in for untested code; it is a real, minimal provider.

## Team tactical profiles are derived from squad features, not match events

**What**: `pipeline/team_profiles.py` computes every squad's `attack_channels`, `ppda`,
`crosses_per_match`, `set_piece_threat`, `aerial` and `danger_players` from its own
players' ability scores and positions (e.g. a squad heavy on strong left-sided
attackers gets a higher left-channel emphasis; press intensity comes from the
midfield/defence group's average ability).

**Why**: DESIGN.md's `team_profiles` table is meant to hold real tactical data mined
from match events (StatsBomb). There's no event-level data source in this build. The
heuristic is fully documented in the module itself and produces internally consistent,
differentiated profiles (verified in `tests/test_graph.py` by opponents actually
having different formations and danger players session to session) rather than one
flat placeholder profile reused everywhere.

## LangGraph checkpointer is MemorySaver, not Postgres

**What**: `graph/graph.py::build_graph` uses `langgraph.checkpoint.memory.MemorySaver`.

**Why**: same root cause as the SQLite vector-store decision above — no live Postgres
in this sandbox to exercise `langgraph.checkpoint.postgres.AsyncPostgresSaver`
against. It's a one-line swap at `build_graph`'s single call site; no node changes.
MemorySaver means sessions don't survive a process restart, which is fine for this
build's own test suite (one process, one run) but not for a real deployment.

## Frontend: plain CSS instead of Tailwind

**What**: `frontend/src/theme.css` is hand-written CSS custom properties and a small
set of reusable classes (`.card`, `.pill`, `.pitch`, `.player-row`, ...), not
Tailwind, even though CLAUDE.md's stack line names Tailwind.

**Why**: time budget. The design tokens (dark background, pitch green, gold, red --
matching the Gaffer mockup built earlier in this project) and the component
shapes were already fully decided; reaching for Tailwind's utility classes would
have meant re-deriving the same values through a different syntax for no behavioural
difference. If this becomes a real multi-contributor frontend, Tailwind's value is
in enforcing consistency across people working in parallel -- worth adopting then,
not clearly worth it for the single `theme.css` file this build has.

## Chat "streaming" over a stub LLM provider

**What**: `POST /sessions/{id}/chat` is a real SSE endpoint (`text/event-stream`,
consumed by `frontend/src/api.ts::chatStream` via the Fetch streaming body reader) --
but the chat node computes the *entire* answer up front (`graph/chat_tools.py::
answer_question`) and the endpoint then emits it word-by-word with a small artificial
delay between tokens.

**Why**: DESIGN.md section 11 specifies SSE for this endpoint, and the transport is
worth building for real even now -- the frontend code that consumes it (an
`EventSource`-style reader assembling tokens into a growing message) is exactly what
a real token-streaming LLM response needs on the client side, so swapping
`StubProvider`/`AnthropicProvider.complete()` for a genuinely streaming call later is
purely a backend change. What's faked here is specifically *where the tokens come
from*, not the protocol between frontend and backend.

## A browser playthrough is why `max_price_eur` and the race-condition fix exist

**What**: `GET /players/search`'s `max_price_eur` parameter and `BuildXI.tsx`'s
stale-search-result guard (see docs/PROGRESS.md Phase 6) both came from actually
playing the game by hand in the browser, not from writing tests against the API in
the abstract.

**Why this is worth saying explicitly**: every other phase's bugs in this build were
caught by automated tests. These two were not test-shaped problems -- the API
behaved exactly as specified in isolation (a `max_price_eur`-less search correctly
returns the top-N-by-ability players; two sequential searches each correctly return
their own results). The bug only exists in the *experience* of a person running out
of budget mid-build, or clicking two pitch slots in quick succession -- which is
specifically the category of problem CLAUDE.md's "play 5 full matches yourself"
instruction for Phase 6 exists to catch, and did.

## Formation-change counter moves use a greedy heuristic, not the ILP

**What**: `engine/counter._greedy_lineup_for_formation` picks each slot's best
available role-fit player greedily, rather than calling `engine/optimizer.py`'s
CP-SAT solver.

**Why**: the optimizer is solving a different, harder problem (budget + nationality
constraints over a huge candidate pool) that needs a real solver; re-fielding a squad
the opponent already owns, with no such constraints, doesn't. Phase 4's 1-second
per-round performance budget made the greedy heuristic the right trade — it's not a
claim of global optimality, and the docstring says so.

## Synthetic data is no longer the silent default

**What**: `pipeline/data_source.py::resolve_source_name()` now defaults to `"real"`;
`DATA_SOURCE=synthetic` must be set explicitly to get fictional players. Every
`pipeline.run_all` run writes a row to the new `ingest_metadata` table (data source,
real-dataset snapshot date if applicable, run timestamp). `api/main.py`'s `lifespan`
refuses to start the API at all if that table is empty (`NotIngestedError`, a clear
message to run the pipeline), and otherwise exposes the most recent row's
`data_source` on `/health` and `app.state`. The frontend shows a persistent "DEMO
DATA — fictional players, not a real opponent" banner on every screen whenever
`/health` reports `"synthetic"`.

**Why**: audited every synthetic-data code path (docs/PROGRESS.md Part 2a) and found
that `pipeline/data_source.py` previously defaulted to synthetic, meaning the
project's own primary documented setup command (`python -m pipeline.run_all`, no
env var) silently produced a fully-fictional game with zero in-app indication —
violating "real gameplay must only ever use real squads." `engine/demo_fixtures.py`'s
Brazil scenario was audited too and is genuinely isolated (only `engine/analyse.py`'s
CLI demo and test files import it; never `graph/`, `api/`, or `pipeline/ingest.py`),
so it needed no change.

**CI/test suite guard**: every test module that calls `run_ingest` now sets
`DATA_SOURCE=synthetic` explicitly at import time (`tests/test_api.py`,
`test_evals.py`, `test_graph.py`, `test_rag.py`) — nothing relies on the new
default, so CI never needs `data_raw/`. `.github/workflows/ci.yml` and
`nightly-eval.yml` set it at the job level for the same reason;
`weekly-pipeline.yml` deliberately leaves it unset (refreshing production *should*
use real data) and now runs `pipeline.download_real_data` first.

**Tests**: `tests/test_lifespan.py` — the metadata-lookup helper directly (empty
table, most-recent-row-wins), and `lifespan()` itself end-to-end against an isolated
engine (refuses to start with no metadata; exposes `data_source` on `app.state` when
present). `frontend/e2e/data-source.spec.ts` — a real re-seed with
`DATA_SOURCE=synthetic` confirms the banner actually renders, on more than one
screen.

## Known limitations

midfield_control, cohesion and balance (36% of overall rating) do not feed expected
goals. Rating and simulated win% can disagree for manual lineup edits (5-7
non-monotonic steps of 17 within the realistic band, confirmed with common random
numbers). The swap optimizer is unaffected (0/20). Planned fix: rating v2 derives
the overall rating from the predicted xG margin (Part 6).

## Thin squads always field exactly 11, with fallback tracked and shown

**What**: `engine/opponent_lineup.py::build_opponent_lineup` fills the opponent's
fixed 4-2-3-1 XI from the drawn squad, falling back to the nearest adjacent
position group (`config.game.POSITION_GROUP_FALLBACK_CHAIN`: DF -> MF -> FW, MF ->
DF -> FW, FW -> MF -> DF) when a slot's native group is too thin, ranking
candidates by `role_fit_score` for the slot being filled rather than raw ability
(reusing the exact penalty mechanism `engine/weaknesses.py` already applies to the
user's own out-of-position picks). Returns `None` only if a squad can't field 11
even after exhausting every fallback group. `graph/nodes.py::draw()` excludes such
squads (logged via `logging.warning`) rather than offering a broken opponent, and
caches fieldability per team_id for the process's lifetime (squads don't change at
runtime). The scouting report shows which slots were filled out of position.

**A real, more serious bug this surfaced**: auditing real-data squad fieldability
found that `draw()`'s own candidate query for UCL mode selected **every row in the
`clubs` table** (`pipeline/real_source.py` populates ~490 of these — every real
club any candidate player happens to play for, not just the 36 actually in the
Champions League), instead of the 36 clubs that actually have a `Squad` row. Before
this fix, a UCL draw had roughly a 93% chance (454/490) of landing on a club with
**zero** squad members, producing a 0-player opponent — a pre-existing, undetected
bug, not something this change introduced. Fixed by querying `Squad.team_id`
(filtered by `tournament`) directly instead of `Club`/`NationalTeam`, which is both
the correctness fix and a performance one (36 squad loads instead of 490).

**Audit numbers, real data** (`docs/PROGRESS.md` Part 2b; updated after the
"5 missing WC2026 teams" fix below — originally measured at 43/48 before that
fix, now 48/48): WC2026 — 48/48 teams fieldable, 0 excluded, 4 needed >=1
out-of-position fill (5 fills total). UCL2025-26 — 36/36 real clubs fieldable,
0 excluded, 2 needed >=1 out-of-position fill (2 fills total). (~454 of ~490
referenced clubs have no `Squad` row at all in this dataset and were never UCL
candidates in the first place — see `docs/PROGRESS.md` Phase 8/6c, not a Part
2b exclusion.)

## 5 real WC2026 teams were missing from the drawable pool

**What**: Haiti, Cape Verde, Ivory Coast, Curaçao and DR Congo — all 5 confirmed
real WC2026 participants in `games.csv.gz` with full real 25-26-player squads
already sitting in `game_lineups.csv.gz` — were silently excluded from the
drawable pool entirely (43/48, not 48/48), discovered when the project owner
asked which 5 teams were missing and asked me to investigate.

**Why**: `pipeline/real_source.py::generate()` only built a `NationalTeam`
entry (and, through it, a `Squad`) for a WC2026 team_id that *also* had a row
in `national_teams.csv.gz` — the dataset's reference table for team display
names. That table only has 124 rows total and doesn't cover every FIFA member
federation; these 5 teams simply aren't in it, even though they unambiguously
played real, recorded WC2026 matches.

**Fix**: `_load_games_team_sets` now also captures each WC2026 team_id's real
name straight from `games.csv.gz`'s own `home_club_name`/`away_club_name`
columns — the same file that already proves the team is a real WC2026
participant — and `generate()` falls back to that name only for a team_id
`national_teams.csv.gz` has no row for. No guessed names, no fabricated data;
just a second real source for the one field (`name`) that was missing.
Everything else (the real squad, from `game_lineups.csv.gz`) was already being
built correctly and simply had nowhere to attach to.

**Result**: WC2026 drawable pool is now a genuine 48/48, all with full real
squads (24-26 players; Haiti landed at 25). One of the 5 (Haiti) needed an
out-of-position fallback fill, consistent with Part 2b's existing mechanism —
nothing else in the fallback/fieldability logic needed to change.

**Tests**: `tests/test_real_source.py` (new) — `_load_games_team_sets` captures
the right WC2026 team name per team_id from a tiny fixture `games.csv.gz`, and
correctly ignores a UCL game's team names in the same file.

**Tests**: `tests/test_opponent_lineup.py` — unit tests for the fallback chain, the
all-native-positions (no fallback) case, and the genuinely-too-thin-to-field-11
case, plus the requested property test: for every team in both modes that the
synthetic seed makes fieldable, the built XI has exactly the 11 formation slots,
all distinct real squad members.

## Real opponent lineups from real match frequency (Part 2c)

**What**: the opponent's predicted XI is now "most frequent starters by formation
from recent matches," not purely best-XI-by-ability. `pipeline/real_source.py`'s
new `_load_starting_lineup_frequency` counts, per candidate player, how many times
they started (`game_lineups.csv.gz`'s `type == "starting_lineup"`, not just
appeared as a substitute) at each position code, across the real WC2026/UCL2025-26
matches already loaded for other stats — reusing `POSITION_CODE_BY_SUB_POSITION`,
the same position vocabulary already mapped from `players.csv`. Persisted into a
new `team_lineup_frequency` table (migration `0003_team_lineup_frequency`),
written by `pipeline/ingest.py`, loaded per-team by
`pipeline/to_engine.py::load_lineup_frequency`.

`engine/opponent_lineup.py::build_opponent_lineup` now takes an optional
`frequency` map and, within whichever fallback tier Part 2b's chain already
selects, ranks candidates by `(start_count_at_this_slot, role_fit_score)` instead
of `role_fit_score` alone — frequency decides the pick when it's nonzero, role-fit
only breaks a frequency tie or fills in when nobody in the tier has recorded
starts. This composes with, rather than overrides, Part 2b's tier order: a
native-position player with zero recorded starts still outranks an
out-of-position player, since frequency is only compared within a tier, never
across tiers.

`graph/nodes.py::draw()` loads this per-opponent frequency map, passes it into
`build_opponent_lineup`, and labels the result `lineup_source = "real"` when at
least `config.game.MIN_REAL_LINEUP_SLOTS` (7 of 11) slots were actually won by
real start-frequency, else `"estimated"` — a handful of frequency-backed slots
isn't enough to call the whole XI "real." This is the exact same XI object
`engine.rating`/`engine.counter`/`engine.simulation` already consume (no second,
possibly-inconsistent lineup computed anywhere); `api/routers.py::scout()` now
reads this computed value instead of the hardcoded `"estimated"` placeholder it
shipped with in Part 2b.

Synthetic data has no real match history, so `SyntheticWorld.lineup_frequency` is
always `None` and every synthetic-seeded team is `"estimated"` — this is the
intended, documented behaviour (`docs/DECISIONS.md` "Synthetic data is no longer
the silent default"), not a gap.

**Audit, real data, both modes** (re-ran `pipeline.run_all` with `DATA_SOURCE=real`
and checked every fieldable team from Part 2b's own audit; updated after the "5
missing WC2026 teams" fix — originally measured at 43/37/6 before that fix):

| Mode | Fieldable | `lineup_source="real"` | `lineup_source="estimated"` |
|---|---|---|---|
| WC2026 (national teams) | 48 | 42 | 6 |
| UCL2025-26 (clubs) | 36 | 35 | 1 |

The 6 WC2026 "estimated" teams and 1 UCL2025-26 "estimated" team are squads whose
candidate pool's recorded WC2026/UCL2025-26 starts don't cover at least 7 of the 11
formation slots in this dataset (sparse match history for some squad members, not
a data bug) — they fall back to ability-only selection for those slots, same as
before Part 2c, and are clearly labelled as such rather than silently presented as
"real."

**Tests**: `tests/test_opponent_lineup.py` — frequency outranks ability within a
tier, `real_fill_count` is zero with no frequency data, `real_fill_count` only
counts slots actually won by frequency (not every player with any recorded row),
`load_lineup_frequency` returns the right counts for the requested team and `{}`
for an unknown one, and a sanity check on the `MIN_REAL_LINEUP_SLOTS` config
constant. Full backend suite: 110 passing, ruff/mypy clean. The existing B1
Playwright check (`frontend/e2e/batch-b.spec.ts`, "opponent's predicted lineup
renders on the scouting screen") re-run against the same real-seeded DB used for
the audit above — still passes.

## RAGAS could not be installed in this environment (Part 3)

**What**: `evals/faithfulness_eval.py` is written against RAGAS's `Faithfulness`
metric (API inspected directly from the 0.4.3 wheel, since the package itself
wouldn't install here), with a `StubProvider` path that needs no RAGAS/LLM call
at all — `StubProvider.complete` is the identity function (`llm/provider.py`), so
the "restyled" report text *is* the engine-grounded template verbatim, faithful
by construction. That path is the one `make eval`/CI actually run, and it's fully
exercised and unit-tested.

**Why the live path couldn't be run here**: `ragas` declares `scikit-network` as
a hard (non-optional, not behind an extra) dependency. PyPI has no prebuilt wheel
for `scikit-network` on any platform — every install builds its Cython
extensions from source, which needs a C++ toolchain (Microsoft Visual C++ Build
Tools on Windows). This machine doesn't have one, and installing a multi-GB
system build toolchain is outside this task's scope. `deepeval` (used by
`evals/numeric_eval.py`'s custom metric) has no such dependency and installed
cleanly.

**What this means for the project owner**: `pip install -e .[eval]` may still
fail on a Windows machine without a C++ toolchain for the same reason. On a
Linux CI runner or a machine with the build tools installed, it should install
and run normally — nothing in `faithfulness_eval.py` is Windows-specific, the
blocker is purely scikit-network's missing wheel. If `ragas` genuinely can't be
installed in the target environment, `run_faithfulness_eval` already degrades to
printing a clear message and returning `None` rather than crashing.

## Golden-set templates carry 2 labelled example rows, not zero

**What**: `evals/golden/retrieval_queries.jsonl` and
`evals/golden/chat_questions.jsonl` (renamed from `retrieval.jsonl`/`chat.jsonl`,
both genuinely empty at the time of rename) each ship with exactly 2 rows marked
`"is_example": true`. Every loader (`evals/retrieval_eval.py::load_golden`, and
anything built on top of it) filters that field out before scoring, so these
rows are never treated as real judged data and a file with only example rows
still counts as empty for every "skip cleanly" check.

**Why**: CLAUDE.md says golden sets are human-written and "do not generate or
edit expected answers" — but the project owner's own Part 3 instructions asked
for "golden set templates (empty, with schema + 2 example lines each)". These
two aren't in conflict: the example rows are clearly labelled illustrations of
the file format, not fabricated ground truth being passed off as real, and the
`is_example` filter means they can never silently inflate a real evaluation
run's numbers.

## CI's E2E job runs `vite dev`, not a production build (Part 4)

**What**: `.github/workflows/ci.yml`'s new `e2e` job starts the frontend with
`npm run dev -- --host 127.0.0.1 --port 5173` (the Vite *dev* server), not
`npm run build && npm run preview`.

**Why**: `frontend/vite.config.ts`'s `/api` -> `http://127.0.0.1:8000` proxy is
declared under vite's `server` config key, which only applies to `vite dev`;
`vite preview` reads a separate `preview` key that this repo has never defined.
Previewing a build would 404 every API call. Readiness is checked with a plain
`curl` retry loop against `/health` and `/` rather than adding the `wait-on` npm
package for one CI step.

## observability.py is a standalone module, not inside engine/llm/rag (Part 5)

**What**: all Langfuse tracing lives in one new top-level `observability.py`,
imported by `graph/nodes.py` (which wraps `engine/` calls), `llm/narrator.py`,
`rag/retriever.py`, `rag/rerank.py`, and `llm/sql_tool.py`.

**Why**: CLAUDE.md's module boundaries say `engine/` must never import `llm/`,
`api/`, or `db/`. `graph/nodes.py` is the layer that calls both `engine/`
functions (`build_analysis`, `run_counter_round`, `simulate_match`) and needs
tracing on them -- if the tracing helper lived inside `llm/`, importing it from
`graph/nodes.py` would be fine (graph/ isn't engine/), but conceptually it
would make `llm/` a dependency of "the thing that traces engine calls," which
reads backwards. A dependency-free leaf module (the same role `config/`
already plays) avoids the question entirely.

## Node-level tracing skips `build`/`user_decision`, traces `chat` only after its interrupt

**What**: `graph/nodes.py`'s `@traced_node` decorator is applied to `draw`,
`validate`, `analyse`, `narrate_report`, `opponent_counter`, `simulate`, and
`narrate_match`, but not to `build` or `user_decision`, and `chat` gets a
manual `traced_span` around only the post-`interrupt()` half of its body.

**Why**: LangGraph's `interrupt()` pauses a node by raising a control-flow
signal that unwinds back through the node function; on resume, the **entire
node function re-executes from the top**, with `interrupt()` now returning the
resume payload instead of raising. `build` and `user_decision` call
`interrupt()` as their literal first statement and do no other work -- wrapping
either in a span would record one span that looks "complete" when the graph
actually just paused, then a second, genuinely complete span on resume: two
trace entries for one logical pause/resume, with the first a misleading
false-error-looking artifact. `chat` does real work (`answer_question`) *after*
`interrupt()` returns, so only that portion -- which only ever runs once per
resume, never during the pausing call -- gets a span.

## Rating v2: built, backtested, and measured as not clearly beating v1 (Part 6)

**What**: `engine/rating_v2.py::RatingV2` (an XGBoost regressor over 18 zone-
average features -- 9 each for the home/away side, same `(vertical,
horizontal)` taxonomy `config.game.Slot`/`engine/zones.py` already use)
predicts a goal margin for a historical matchup, calibrated via a logistic
win-probability fit (`Calibration`) into a 0-100 "overall" -- replacing only
v1's `overall` field, not its sub-ratings (those stay exactly `RatingV1`'s own
output; the weaknesses/swaps/narration machinery that reads them needed no
change). `pipeline/rating_v2_dataset.py` builds the training set from the real
Transfermarkt export's *entire* match history (not just the current WC2026/
UCL2025-26 season -- rating v2 needs volume): 8,680 real historical matches
where at least 6 of each side's 11 starters are players this project already
has an `ability_score` for. No real shot-level xG exists in this dataset
(`pipeline/real_source.py`'s own docstring already says so), so the regression
target is the actual **goal margin** -- a measured substitute, not a guessed
one.

**Backtest** (`pipeline/train_rating_v2.py`, 80/20 train/test split, seed 42,
6,944 train / 1,736 test examples): v1 here means its own weighted sub-rating
formula restricted to the 3 sub-ratings computable from zone-average data alone
(attack/midfield_control/defence -- matchup/cohesion/balance all need live
context, like the opponent's threat map or role_fit, that a historical result
alone doesn't carry), re-normalized to sum to 1, and turned into a margin via
`home_proxy_overall - away_proxy_overall` for a fair side-vs-side comparison.

| | Correlation with actual goal margin | Brier score (lower is better) |
|---|---|---|
| v1 (proxy) | 0.3311 | 0.2284 |
| v2 (XGBoost) | 0.3409 | 0.2364 |

Top 5 SHAP features by mean \|value\|: `home_att_center`, `away_mid_center`,
`home_def_center`, `away_def_center`, `away_att_center` -- center-channel
features dominate, consistent with `config/game.py`'s own formations putting
the most players through the center of the pitch.

**Verdict: v2 does not beat v1**, and the live default (`engine/rating.py::
get_default_rating_model()`) stays `RatingV1`, per the project owner's own
instruction ("swap in through the RatingModel interface only if it beats v1;
otherwise keep v1"). v2 improves correlation with the real outcome by a real
but narrow margin (+0.0098, about 3% relative) while its Brier score is
measurably *worse* (0.2364 vs 0.2284) -- an improvement on one axis and a
regression on the other is a trade-off, not a win. The bar applied here is
deliberately strict: v2 must improve correlation **and** not regress
calibration to count as "beats v1"; a result this mixed doesn't clear it.

This also sidesteps a real engineering cost that a narrow win wouldn't have
justified: `get_default_rating_model()` is synchronous and called from many
places with no database access (`engine/` may not import `pipeline/`/`db/`,
CLAUDE.md's module boundaries) -- making `RatingV2` the live default would need
an async, lazily-cached loader wired into `graph/nodes.py` with a safe fallback
to v1 when real data isn't available (always true in CI/synthetic contexts).
`RatingV2` is fully implemented and usable through the exact same `RatingModel`
protocol `RatingV1` is, so that wiring is there to do cheaply if a future
backtest (more data, a richer feature set) shows a clearer win.

**Reproducibility**: no trained model is committed anywhere. `make
train-rating-v2` (needs the real dataset: `python -m pipeline.download_real_data`,
then `DATA_SOURCE=real python -m pipeline.run_all`) retrains and re-backtests
from scratch every time, from the same real data and the same seed --
`evals/reports/rating_v2_backtest.json` (gitignored, like every other
`evals/reports/` output) is regenerated, not restored.

**Tests**: `tests/test_rating_v2_dataset.py` (zone-feature averaging and the
coverage threshold, plus an end-to-end run against a tiny fixture gzip CSV
pair -- not the real 126MB files), `tests/test_rating_v2.py` (calibration math,
including a real `OverflowError` this caught on its first run and fixed --
`math.exp` on an unclipped logit overflows for an extreme margin times a steep
slope -- and `RatingV2.rate()` against a fake model), `tests/
test_train_rating_v2.py` (the pure helper functions, and `run_backtest()`'s
"not enough real data" skip path). None of these need the real dataset to run
in CI.

## Postgres + pgvector + Langfuse v4, verified live -- 5 real bugs found and fixed

**What**: Docker became available partway through this project (it wasn't
reachable in the sandbox this build was originally developed in -- see "SQLite
fallback" above), so the Postgres/pgvector path and a real Langfuse instance
were exercised live for the first time, end to end: `docker compose up -d`,
`alembic upgrade head`, the full real-data pipeline, the full `pytest` suite,
the full Playwright E2E suite, and a real session's traces checked in the
actual Langfuse UI. Every one of these had been *written* against the
possibility of Postgres/Langfuse, per CLAUDE.md's "keep both paths working,"
but never actually run against them -- five real, previously-undetected bugs
surfaced in the first hour of doing so, all specific to the Postgres/Langfuse
code paths (the SQLite/no-op paths these mirror were never affected and still
pass every existing test).

1. **`documents.metadata_json` as plain `json`, not `jsonb`.** Postgres has no
   default GIN operator class for plain `json`, so migration `0001`'s own
   `CREATE INDEX ... USING gin (metadata_json)` failed outright on its first
   real run. Fixed in `db/models.py`: `JSON().with_variant(JSONB, "postgresql")`
   -- SQLite keeps the generic `JSON` type it always used; Postgres gets
   `jsonb`, which the GIN index actually supports.
2. **Three `DateTime` columns inserting timezone-aware values into
   timezone-naive columns.** `GameSession.created_at`, `IngestMetadata.
   pipeline_run_at`, and `EvalRun.created_at` all default to `dt.datetime.now(
   dt.UTC)` (correctly timezone-aware) but were declared as plain `DateTime`
   (timezone-naive). SQLite never complained (it has no real datetime type, just
   stores whatever string/object it's given); `asyncpg` does, and raised `can't
   subtract offset-naive and offset-aware datetimes` on the very first ingest
   pipeline run against Postgres. Fixed by declaring all three
   `DateTime(timezone=True)`.
3. **`rag/dense.py`'s Postgres branch used a raw string in `order_by`.**
   `order_by("sim DESC")` is no longer accepted by modern SQLAlchemy without
   `text()` -- a `CompileError` on the very first real pgvector query. Fixed by
   keeping the labelled `sim` expression as a Python object and calling
   `sim.desc()` on it directly, which also let the same object be reused for
   both the `SELECT` list and the `ORDER BY` clause instead of being
   re-declared.
4. **The same Postgres branch silently dropped the `doc_type` filter.** It
   built a fresh `select(...)` from scratch instead of reusing/extending the
   SQLite branch's already-filtered `stmt` -- a metadata-filtered dense search
   on Postgres would have silently searched the *entire* corpus regardless of
   `doc_type`. Fixed by applying the same conditional `.where(Document.doc_type
   == doc_type)` to the Postgres statement too.
5. **`Document.embedding.op("<=>")(...)` has no declared return type**, so
   SQLAlchemy infers the result type of the whole `1 - (...)` expression from
   the *left* operand -- `VectorType` -- including the literal `1`'s own bind
   parameter. `VectorType`'s Postgres bind processor expects a list and crashes
   on an `int` (`'int' object is not iterable`). Fixed with `op("<=>",
   return_type=Float)`, so only the actual vector operand gets `VectorType`'s
   bind processor and the literal `1` is bound as a plain float.
6. **`observability.py::_client()` validated Langfuse settings but never
   passed them to the SDK.** `get_client()` (no arguments) reads
   `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`/`HOST` from `os.environ` directly --
   but `config.settings` reads `.env` into its own Pydantic model and never
   mutates the process environment, so every trace silently initialized
   disabled ("Authentication error: ... initialized without public_key") no
   matter how correctly `.env` was configured. Every test and every manual
   check before this one used a *fake* client (Part 5's own test suite,
   deliberately, since no real instance existed yet), so this was invisible
   until a real instance existed to check against. Fixed by constructing
   `Langfuse(public_key=..., secret_key=..., host=...)` explicitly with
   `config.settings`'s own values instead of relying on `get_client()`'s
   implicit environment-variable discovery.

**A sixth, non-bug finding worth recording**: once tracing was *actually*
wired up end to end, the first `draw()` call after a fresh server start
measurably slowed down (enough to flake a Playwright assertion with a 5s
timeout) -- the Langfuse client's first construction does real client/network
setup, not just object allocation, and that cost was previously invisible
since `_client()` never did anything real. Fixed by calling the new
`observability.warm_up()` once during `api/main.py`'s `lifespan` startup
instead of paying that cost on whichever request happens to hit `traced_span`
first.

**Also found and fixed**: `tests/test_observability.py` had four tests
asserting "without configured keys" behaviour that implicitly depended on
the local `.env` never having real Langfuse keys in it -- true by accident
until this verification, false the moment a real `docker-compose.yml`
Langfuse instance got configured for local use. Added an autouse
`conftest.py` fixture (`_no_real_langfuse_calls`) that forces
`observability._client` to `None` for every test by default, so the whole
suite's determinism no longer depends on what happens to be in a developer's
own `.env` -- tests that exercise the "configured" path already override this
per-test with their own `monkeypatch.setattr`, which simply wins.

**Verified, concretely**: `docker compose up -d` brings up 8 healthy
containers (the app's own `postgres`/`redis`, plus Langfuse's `langfuse-web`/
`langfuse-worker`/`langfuse-postgres`/`langfuse-redis`/`clickhouse`/`minio`);
`alembic upgrade head` creates all 15 tables, the `vector` extension (0.8.7),
the `gaffer_ro` role, the GIN index, and the HNSW index
(`ix_documents_embedding_hnsw ... USING hnsw (embedding vector_cosine_ops)`);
the full real-data pipeline populates 4,755 players / 490 clubs / 48 national
teams / 2,595 squad rows / 4,839 documents (every one with a non-null
embedding) against live Postgres; a hybrid retrieval query with metadata
filters (`doc_type="player_profile"`, `nationality="Brazil"`) returns real,
correctly-filtered results via `method="hybrid_rerank"` against the pgvector
HNSW path, not any in-memory fallback (`session.bind.dialect.name ==
"postgresql"` confirmed); the full `pytest` suite (152 tests) and the full
Playwright E2E batch (6/6) both pass against the Postgres-backed app; and a
real Playwright session's traces -- `node.draw`, `node.validate`, `node.
analyse`, `node.narrate_report`, `node.opponent_counter`, `node.simulate`,
`node.narrate_match`, `node.chat`, with `llm.narrate` (type `GENERATION`) and
`rag.retrieve` (type `RETRIEVER`) nested underneath -- were confirmed by
signing into the real Langfuse UI and reading them directly, not inferred
from logs.

**Langfuse version note**: `docker-compose.yml` previously pinned
`langfuse/langfuse:2`, the pre-OTLP self-hosted image, while the installed
Python SDK is 4.16.0 (OTEL/OTLP-based) -- incompatible outright, which is
exactly bug #6 above's root cause once actually tested. Replaced with the
official Langfuse v4 self-host composition (`docker.langfuse.com/langfuse/
langfuse:4` + `langfuse-worker:4`, their own Postgres/Redis, ClickHouse, and
MinIO for S3-compatible event storage) fetched from Langfuse's own
`docker-compose.yml` and adapted: service names prefixed/renamed to avoid
port collisions with the app's own `postgres`/`redis` (both stacks would
otherwise fight over 5432/6379), dev-only credentials throughout matching
this repo's existing placeholder style, and `LANGFUSE_INIT_*` env vars so a
fresh `docker compose up -d` auto-provisions a usable org/project/API-key/
user without a manual sign-up step. Also fixed along the way: the official
image reference for MinIO on Docker Hub (`minio/minio`) no longer exists
(`pull access denied`) -- replaced with `cgr.dev/chainguard/minio`, matching
upstream's own current compose file; and `langfuse-web`'s healthcheck
initially failed because Next.js's standalone server binds to `$HOSTNAME`
when set (Docker defaults this to the container id, which resolves to the
container's own IP, not "every interface") -- fixed with an explicit
`HOSTNAME=0.0.0.0` override.

## Season stat window shrunk from 440 to 365 days; ability score gets minutes shrinkage and position recalibration (Part 2 Step A/B)

**What (Step A, diagnosis)**: `pipeline/real_source.py::_aggregate_real_stats` summed
`goals`/`assists`/`minutes` from `appearances.csv.gz` across every row in a 440-day
window with no season boundary check. Investigated after the project owner noticed
Harry Kane showing 68 goals in a single "season." Broken down against the raw rows:
68 = 39 (Bundesliga) + 15 (Champions League) + 7 (DFB-Pokal) + 3 (Club World Cup) +
3 (international caps) + 1 (Supercup), and the date range in that window
(2025-04-16 to 2026-06-27) spans parts of two league seasons, not one. Same pattern
confirmed across all top-20 scorers (every one spread 3-6 competitions) and for
assists (Olise: 41 reported vs. 26 in Bundesliga alone).

**What (Step B, fix)**: three changes, each per the project owner's explicit choice
after being shown the diagnosis and alternatives:
1. `APPEARANCE_LOOKBACK_DAYS` 440 -> 365 (`pipeline/real_source.py`). The project
   owner chose to keep summing across every competition a player appeared in
   (league + cup + continental + international caps) rather than restricting to one
   competition -- that's a deliberate design choice now documented in the module's
   own docstring, not a bug. Confirmed empirically: at 365 days Kane's total drops
   from 68 to 63 (the 5-goal difference being exactly the tail of the *previous*
   season that the 440-day window double-counted).
2. Minutes shrinkage (`config.game.ABILITY_MINUTES_SHRINKAGE_K = 900`,
   `pipeline/features.py::_minutes_shrinkage_weight`): a full-coverage player's
   percentile-ranked composite is pulled toward 50.0 by weight
   `minutes/(minutes+900)`. Found concretely before this existed: Marcelino Núñez
   reached `ability_score=74.4` off 90 minutes -- the existing `confidence` field
   flagged this (0.75) but nothing downstream ever used it to discount the number.
3. Position recalibration (`pipeline/features.py::compute_features`): the weighted
   sum of per-metric percentiles ("the composite") is now itself re-percentile-ranked
   within its position group before becoming `ability_score`, instead of being used
   directly. The per-position `ABILITY_WEIGHTS` formulas mix a different number of,
   and differently-correlated, components (GK: 3 mutually-reinforcing defensive
   metrics; FW: 4 metrics a single attacking profile rarely maxes simultaneously),
   so the raw composite's distribution shape differs by position even though each
   component is individually a 0-100 percentile. Found concretely before this fix:
   GK and DF cleared `ability_score>=90` at up to 4.7x FW's per-capita rate despite
   every group's mean already being ~49.6-49.8 by construction; Robin Risser (GK,
   0 goals, 1 assist) ranked above Ousmane Dembélé and a 68-goal Harry Kane.

**Measured effect, real data, before vs after** (full tables in the session
transcript): top 20 overall was GK/DF-dominated (14 of 20); now spans all four
groups (4-7 each). No sub-450-minute player in the top 100 (was 1, now 0). Cross-
position spread of `ability_score>=90` is noisy at that literal cutoff (4.3x, small
counts at an extreme tail now that the ceiling itself dropped from 96.5 to 91.3) but
1.3x-1.6x at >=85/>=80. Kane: 63 goals, matching the raw 365-day window exactly.

**Downstream consequence this surfaced, fixed the same session**: ability_score
compressing at the top end (max 96.5 -> 91.3) compressed the XGBoost-predicted
`ability_value` pricing component much more than real `market_value_eur` (unaffected,
still real Transfermarkt data) -- elite prices dropped (top price €93M -> €82M)
while median-starter prices barely moved, so the same €1B budget suddenly afforded
16 top-2%-ability players alongside 8 median starters (target: 4-6) and the
unconstrained best-XI cost fell to €718M (target: >=€1.5B). Tested whether adjusting
`BUDGET_EUR` alone could fix this instead -- it can't: the >=€1.5B check depends on
the players' priced value, not the budget, and the top-11 elites only total €718M
regardless of budget level. Fixed by reweighting `PRICING_ABILITY_WEIGHT`/
`PRICING_MARKET_WEIGHT` from 0.7/0.3 to 0.1/0.9 (tested the full range from 0.5/0.5
to 0.0/1.0 first; 0.1/0.9 is the least extreme split that clears both checks -- 0.2/0.8
still leaves 7 elites affordable, just outside target). This substantially dilutes
DESIGN.md section 7.2's original "de-biased pricing" intent (predicting value with
age/club-strength neutralized specifically to correct for market-value bias) down to
10% influence -- a real trade-off, approved explicitly by the project owner after
seeing the predicted-vs-measured numbers for several alternative weights.

**Tests**: `tests/test_real_source.py` -- `_aggregate_real_stats` sums rows inside
the one-season window once each across competitions (the deliberate cross-
competition choice), and excludes a row one day outside the window. Found and fixed
a pre-existing, unrelated test-isolation bug while re-running the full suite:
`tests/test_pipeline.py` never set `DATA_SOURCE=synthetic` (unlike every other test
module that seeds a database), so running it in isolation read `DATA_SOURCE=real`
from `.env` and ingested the real 48-team dataset instead of the synthetic 12-team
world its assertions expect -- it only passed as part of the full suite because an
earlier-imported test module's own override happened to leak forward through
`os.environ`. Fixed by adding the same explicit override every other test module
already has.

## Part 2 Step C: pricing reweight applied; rating calibration re-verified clean

**What**: the 0.1/0.9 `PRICING_ABILITY_WEIGHT`/`PRICING_MARKET_WEIGHT` reweight
proposed above was applied after the project owner's explicit approval (shown the
predicted-vs-measured numbers for 0.7/0.3 through 0.0/1.0 first). Prices
recomputed against live Postgres: budget sanity now passes both checks --
6 top-2%-ability players afford alongside 8 median starters (target 4-6, was 16),
unconstrained top-11-elite XI costs EUR1.506B (target >=EUR1.5B, was EUR718M).
`team_profiles` and `documents` -- left empty after Step B's truncate, gated
behind this approval -- were regenerated (84 team profiles, 4839 documents, all
embedded).

**Rating calibration re-verified** (the exact Iran/Türkiye pair docs/DECISIONS.md's
earlier rebalance passes used, true-optimal lineup via `engine.optimizer.
find_optimal_lineup`, lowest-ability legal lineup as "worst"): all four targets
pass after the ability-score and pricing changes --

| | optimal win% | worst win% | gap |
|---|---|---|---|
| weak (Iran) | 75.0% (target 75-85%) | 51.4% | 23.6pts (target >=15) |
| strong (Türkiye) | 63.7% (target 55-65%) | 40.5% | 23.2pts (target >=15) |

Weak-opponent win% lands right at the lower edge of its target window, not
comfortably mid-range -- worth knowing if a future change nudges ability scores or
pricing again, since there's no headroom left on that side before it would miss.

## Part 1 latency follow-up: dropped `evaluate_swap` as a standalone chat tool

**Why**: the live chat-agent verification (`evals/reports/chat_verification_2026-
11-03.md`) measured p95 latency at 7.34s against a <6s target. `llm/chat_agent.py`
exposed both `evaluate_swap` ("Evaluate swapping... Returns the rating change")
and `simulate_what_if` ("Evaluate swapping... returning both the rating change AND
the updated win/draw/loss simulation") to the model as separate tools with nearly
identical descriptions and identical input schemas. `simulate_what_if`'s own
implementation (`_tool_simulate_what_if`) already calls the exact same
`_tool_evaluate_swap`/`evaluate_swap()` helper internally before adding the
simulation on top -- it was never anything but a strict superset of
`evaluate_swap`, computed in one tool execution, not an extra round-trip. With
both offered, nothing in the schema told the model that `evaluate_swap` was
redundant once `simulate_what_if` existed; a plausible path for a what-if question
is the model picking `evaluate_swap` first for the rating, then realizing (or
being asked) about match outcome and calling `simulate_what_if` next for the same
swap -- two sequential real Anthropic API calls where one suffices. The report's
`f2` row shows a different but related symptom already happening in practice: the
model called the *same* tool (`evaluate_swap`) twice for one question.

**Decision**: remove `evaluate_swap` from the model-facing `TOOLS` list and from
`_TOOL_DISPATCH` in `llm/chat_agent.py`. `simulate_what_if` is now the only tool
for any swap/what-if question, rating-only phrasing included, and its description
was rewritten to say so explicitly and to tell the model never to call it twice or
follow it with a second call for the same swap. The underlying `_tool_evaluate_swap`
Python function, and `graph/chat_tools.py`'s `evaluate_swap()` engine call it
wraps, are both untouched and still used -- only `_tool_simulate_what_if` calls
them now, directly, same as before. No rating/engine/swap-evaluation logic changed.

**Alternatives considered**: tightening both tools' descriptions to disambiguate
when to use which, instead of removing one. Rejected because disambiguation by
prompt wording is probabilistic -- it can reduce but not guarantee against the
model picking the "wrong" one first and the superset tool second for the same
question, which is exactly the failure mode costing the round-trip. Removing the
redundant tool from the model's choice set removes the possibility entirely
rather than just making it less likely, at no cost (the engine-side compute
`simulate_what_if` does beyond `evaluate_swap` -- one more lineup rating and
match simulation -- is local, deterministic, and cheap next to an Anthropic
round-trip).

**Not done / needs the project owner**: re-running the live verification suite to
confirm the p95 number actually drops below 6s (CLAUDE.md: live LLM runs are
opt-in by hand, not run as part of this task). `docs/PROGRESS.md` has the exact
command and what to look for in the regenerated report.

## Player search silently dropped any player outside the global top-400-by-ability

**What**: `pipeline/to_engine.py::load_candidate_pool` ran `ORDER BY ability_score
DESC LIMIT 400` in SQL, then `GET /sessions/{id}/players/search`
(`api/routers.py::search_players`) filtered that already-truncated 400-row list by
the user's search text in Python. A player whose ability score put them outside
the global top 400 could never be found by name, however exact the search --
proved concretely against this session's live, running app: the seeded data has
two players named "Jude Diallo" (ability 68.9 and 13.2); searching "Jude Diallo"
only ever returned the 68.9 one, because the 13.2 one (rank 829 of 830) never
survived the SQL-level cap before the name filter even ran. Found while
investigating the project owner's report of not being able to find specific real
players (Virgil van Dijk, Arda Güler) by name in Champions League mode -- this is
one of the two plausible code-level causes identified (the other, more likely for
expensive real stars: the "Affordable only" search toggle, on by default, silently
hiding anything over budget -- not a bug, working as designed per the "A real
product gap, not just a bug" fix in `docs/PROGRESS.md`'s Phase 6c manual
playthrough). Could not confirm which actually applied to those two specific
players -- this session runs on synthetic data; the real-dataset host
(`pub-e682...r2.dev`) returns HTTP 403 from this sandbox.

**Fix**: `load_candidate_pool` takes a new optional `name_query` parameter and
applies it in the SQL `WHERE` clause, before the ability-sorted `LIMIT`, instead of
after. `search_players` passes its `q` query param through as `name_query` instead
of filtering the already-capped Python list. The ability-sorted cap itself is
unchanged and still applies to every other caller (`engine.optimizer`'s candidate
pool, the no-query browsing case) -- it's a legitimate, by-design "top N by
ability" cap for browsing, just no longer allowed to make a *named* search of the
full player table silently incomplete.

**Not done**: this doesn't address two related, lower-priority gaps noticed while
fixing this, both out of scope for the reported bug: (1) `position_group`
filtering still happens in Python after the same ability-sorted cap, derived from
`Player.positions[0]` which isn't trivially expressible as a SQL `WHERE` without
duplicating `pipeline/features.py::_group`'s code->group mapping in SQL -- a
specific position (most likely GK, which skews rare) could in principle be
under-represented in the top-400-ability pool the same way names used to be; (2)
the no-query browsing case still only ever shows the top 400 by ability with no
pagination or total-count indicator, which is an intentional product choice, not a
bug, but worth the project owner knowing it's still true.

## Budget lowered from €1B back to €500M

**What**: `config/game.py::BUDGET_EUR` is `500_000_000` again (was
`1_000_000_000`, see "Budget raised from €500M to €1B" above). Updated everywhere
that number was duplicated: `frontend/src/screens/BuildXI.tsx`'s local fallback
constant, the three Playwright e2e specs that hardcode their own copy for
client-side affordability simulation (`frontend/e2e/{batch-a,batch-b,full-session}
.spec.ts`), `CLAUDE.md`'s one-line project summary, `docs/DESIGN.md` section 1's
rules table, and `README.md` (the intro paragraph and the game-rules table; the
real-data budget-sanity-check row in README's eval results table was left as its
own explicitly-€1B-labelled historical measurement, flagged stale instead of
silently rewritten, since re-measuring it needs the real dataset this sandbox
currently can't reach).

**Why**: explicit user instruction ("1 billion is too much").

**Effect, measured not assumed**: re-ran `pipeline.pricing`'s budget sanity check
against the synthetic world at the new €500M budget, using the *current* pricing
curve (post Part 2 Step B/C's ability-score recalibration and
`PRICING_ABILITY_WEIGHT`/`PRICING_MARKET_WEIGHT` reweight, both well after the
original €500M→€1B raise above). Result: only 1 elite (top-2%-ability) player is
affordable alongside 8 median starters at €500M now -- tighter than even the
original pre-recalibration €500M measurement (~2), and well short of
`docs/DESIGN.md` section 1's original "~3 elite + 8 good" target. The pricing
curve itself was not touched or re-tuned; this is reported, not acted on, per the
same "measure, don't assume" convention the original raise used -- the project
owner may want the pricing curve re-tuned for €500M specifically, but that's a
separate decision not requested here.

## API endpoints that resume the LangGraph thread must check the pending interrupt before resuming, not after

**What**: `api/routers.py`'s `/lineup/analyse`, `/decision`, `/chat`, and
`/chat/end` -- the four endpoints that call `graph_.ainvoke(Command(resume=...))`
-- each now call a new `_pending_awaiting(graph_, session_id)` helper first and
return a 409 if it doesn't match what that endpoint is about to resume
(`"lineup"` / `"decision"` / `"question"`). `graph/nodes.py`'s `build`,
`user_decision`, and `chat` nodes also now raise a named `ResumeMismatch`
(`graph/state.py`) instead of doing a bare `payload["key"]` lookup, as defense in
depth, and the four endpoints catch it as a fallback 409.

**Why**: found live, while verifying the Render deploy's chat endpoint by hand --
calling `/chat` while the session's thread was still paused at the "lineup"
interrupt (i.e. before `/lineup/analyse` had been called) threw an uncaught
`KeyError` inside `graph/nodes.py`'s `chat()` node. From `/chat` specifically this
surfaced as a silent `200 OK` with an empty SSE body: the exception fires inside
`event_stream()`'s async generator, which only runs once FastAPI starts iterating
it to send the response -- by then headers are already committed, so the error
can't become a proper status code, and the client sees nothing happened.

**Why checking first, not just catching the exception after**: a first attempt
wrapped the `ainvoke(Command(resume=...))` calls in `try/except ResumeMismatch`
and nothing else. A regression test proved this insufficient: once a mismatched
`Command(resume=...)` reaches a node and that node raises *any* exception
(`KeyError` or the new named one), LangGraph has already consumed the pending
interrupt for that thread -- the task fails, and the thread is left unable to
resume even a subsequent, correctly-shaped request. The only way to avoid
corrupting the thread is to never send the mismatched resume into the graph in
the first place.

**Why `_pending_awaiting()` and not the existing `_awaiting()`/`_current_state()`
helpers**: a first version of the pre-check used `_awaiting(_current_state(graph_,
session_id))` and broke multiple legitimate flows (every test calling
`/lineup/analyse` or `/decision` in the normal, correct order started failing with
409s). Root cause: `_current_state()` returns `dict(snapshot.values)` from
`graph_.get_state(config)`, but a direct introspection of this project's installed
LangGraph (1.2.12) showed the pending interrupt lives on `snapshot.interrupts`,
*not* inside `snapshot.values` -- `_awaiting()`'s `state.get("__interrupt__")`
lookup only ever finds something when `state` is the dict `ainvoke()` itself
returns (which does carry a `__interrupt__` pseudo-key), never on a `get_state()`
snapshot's `.values`. `_current_state()`'s old docstring claimed it included
`__interrupt__`; that was never true for this LangGraph version and nothing had
exercised the combination until now. `_pending_awaiting()` reads
`snapshot.interrupts[0].value` directly instead.

**Not done**: the frontend doesn't currently have a way to trigger this out of
normal use (its own flow always calls these endpoints in order), so this is a
backend robustness fix for double-clicks/retries/race conditions and direct API
use, not a response to an observed frontend bug.
