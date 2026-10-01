# Decisions

Format: what, why, where it lives.

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

## Formation-change counter moves use a greedy heuristic, not the ILP

**What**: `engine/counter._greedy_lineup_for_formation` picks each slot's best
available role-fit player greedily, rather than calling `engine/optimizer.py`'s
CP-SAT solver.

**Why**: the optimizer is solving a different, harder problem (budget + nationality
constraints over a huge candidate pool) that needs a real solver; re-fielding a squad
the opponent already owns, with no such constraints, doesn't. Phase 4's 1-second
per-round performance budget made the greedy heuristic the right trade — it's not a
claim of global optimality, and the docstring says so.
