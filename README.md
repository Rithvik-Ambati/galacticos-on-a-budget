# Gaffer — Galácticos on a Budget

[![CI](https://github.com/Rithvik-Ambati/galacticos-on-a-budget/actions/workflows/ci.yml/badge.svg)](https://github.com/Rithvik-Ambati/galacticos-on-a-budget/actions/workflows/ci.yml)

> Build an XI to beat a real opponent. Get coached, get countered, play it out.

## What it is

You're assigned a real opponent — a real World Cup 2026 national squad or a real
2025/26 Champions League club. Build an XI from anyone else on earth, under a €1B
budget. A coach tells you exactly where your lineup breaks (weak zones, out-of-position
picks, budget left on the table) and suggests legal swaps. The opponent counters back
using its own real squad. Then you simulate the match and read a report on what
actually happened.

**Core principle: the engine decides, the LLM explains.** Every number shown to the
user — ratings, prices, percentages, scorelines — is produced by deterministic,
tested code or a validated model. The LLM only narrates engine output, answers
follow-up questions using retrieved context, and translates questions into read-only
SQL. It is never asked to produce a number itself, on any provider.

Full spec: [`docs/DESIGN.md`](docs/DESIGN.md). Build log, every bug found and fixed,
and the reasoning behind every non-obvious choice: [`docs/PROGRESS.md`](docs/PROGRESS.md)
and [`docs/DECISIONS.md`](docs/DECISIONS.md) — read those before this file if you want
the real story; this one is the summary.

## Screenshots

> TODO: pending screenshots — paste a PNG/GIF per screen here once captured
> (Welcome → Scouting → Build → Coach's Report → Match Day → Match Report).

| Welcome | Scouting report | Build your XI |
|---|---|---|
| _screenshot placeholder_ | _screenshot placeholder_ | _screenshot placeholder_ |

| Coach's report | Match day | Match report |
|---|---|---|
| _screenshot placeholder_ | _screenshot placeholder_ | _screenshot placeholder_ |

## Architecture

```mermaid
flowchart TD
    FE["React frontend<br/>(Vite + TS)"] -->|"/api proxy"| API["FastAPI backend"]
    API --> Graph["LangGraph orchestrator<br/>(game state, loops, interrupts, checkpointing)"]
    API --> Redis[("Redis cache")]
    Graph --> Engine["Analysis engine<br/>(rules, rating, weaknesses, swaps, counter, simulation)"]
    Graph --> RAG["Hybrid RAG<br/>(BM25 + dense, RRF fusion, cross-encoder rerank)"]
    Graph --> LLM["LLM layer<br/>(coach/match narration, chat, text-to-SQL)"]
    Engine --> DB[("Postgres + pgvector<br/>(SQLite fallback)")]
    RAG --> DB
    LLM --> DB
    Pipeline["Weekly data pipeline<br/>ingest → features → prices → documents → embeddings"] --> DB
    Graph -. traces .-> Langfuse["Langfuse"]
    LLM -. traces .-> Langfuse
    RAG -. traces .-> Langfuse

    classDef store fill:#1a2430,stroke:#3ddc84,color:#f2f5f7;
    class DB,Redis store;
```

Repo layout mirrors this: `pipeline/` → `engine/` → `rag/` + `llm/` → `graph/` → `api/`
→ `frontend/`, plus `db/` (models + migrations), `config/` (every tunable number),
`observability.py` (Langfuse tracing), `evals/` and `tests/`. `CLAUDE.md` is the
standing rulebook Claude Code read on every phase of this build — the single most
load-bearing file in the repo if you want to understand *why* things are shaped the
way they are.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI + Pydantic | Async-native, request/response validation for free, and the same models double as the engine's own schemas |
| Orchestration | LangGraph | The game is a state machine with human-in-the-loop pauses (build lineup, counter-or-lock-in, chat) — `interrupt()` + checkpointing fits that directly, instead of hand-rolling session state |
| Database | Postgres + pgvector (SQLite fallback) | One store for relational data *and* vectors — no separate vector DB to run or keep in sync |
| Retrieval | `rank-bm25` + `sentence-transformers` + cross-encoder rerank | Hybrid lexical+semantic beats either alone; the rerank step fixes the long tail RRF fusion alone misses |
| Constraint solving | OR-Tools CP-SAT | Finding the best *legal* lineup (budget, nationality cap, formation) is a real constraint-satisfaction problem, not a sort |
| Rating v1 | Hand-weighted sub-ratings | Transparent, debuggable, and needs zero training data to ship |
| Rating v2 (built, not swapped in) | XGBoost + SHAP | Learns real opponent-interaction effects from historical match results — see `docs/DECISIONS.md` for why it didn't clear the bar to replace v1 |
| LLM | Anthropic, behind a `StubProvider` for dev/CI | Narration only, never numbers (CLAUDE.md rule 1) — the stub makes every behavior test deterministic and free |
| Observability | Langfuse | One trace per game-session node, LLM/retrieval/rerank/SQL-tool spans nested underneath automatically |
| Frontend | React + Vite, plain CSS | Fast dev loop for a UI this size; Tailwind's setup cost wasn't worth it at this scope |
| CI | GitHub Actions | Lint/typecheck/test/Playwright/eval gates on every push, a nightly full eval run |

## How to run it

**Primary path: Docker Compose** (Postgres 16 + pgvector 0.8, Redis, and a full
Langfuse v4 self-host — ClickHouse, MinIO, their own Postgres/Redis). Verified
end-to-end against a live stack, not just written:

```bash
docker compose up -d          # postgres, redis, langfuse-web/worker + their own stack
pip install -e .
cp .env.example .env          # then fill in DATABASE_URL/REDIS_URL/LANGFUSE_* -- see below
alembic -c db/alembic.ini upgrade head   # creates tables, the pgvector extension, the HNSW index
python -m pipeline.download_real_data    # 241MB, once
python -m pipeline.run_all               # seeds Postgres -- DATA_SOURCE defaults to "real"
```

`.env`'s Postgres/Redis/Langfuse values, matching `docker-compose.yml`'s dev-only
credentials:

```bash
DATABASE_URL=postgresql+asyncpg://gaffer:gaffer@localhost:5432/gaffer
DATABASE_URL_READONLY=postgresql+asyncpg://gaffer_ro:gaffer_ro@localhost:5432/gaffer
REDIS_URL=redis://localhost:6379/0
LANGFUSE_PUBLIC_KEY=pk-lf-gaffer-dev-0000000000000000
LANGFUSE_SECRET_KEY=sk-lf-gaffer-dev-0000000000000000
LANGFUSE_HOST=http://localhost:3000
```

(`gaffer_ro` is created by the first migration; the Langfuse keys above are
auto-provisioned on `langfuse-web`'s first boot via `LANGFUSE_INIT_*` env vars in
`docker-compose.yml` — no manual sign-up needed. Sign in at
`http://localhost:3000` with `dev@example.com` / `dev-password-change-me` to
browse traces yourself.)

Then, in two more terminals:

```bash
make api                              # http://localhost:8000
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to :8000
```

**Fallback path: SQLite, no Docker needed** — `make setup` (pip install, download
the real dataset, seed `dev.db`), then the same `make api` / `npm run dev` above.
This is what the automated fresh-clone verification in this repo's history
actually used (Docker wasn't reachable in that sandbox at the time); the Postgres
path above has since been verified live in the same environment once Docker was
available — see `docs/DECISIONS.md` "Postgres + pgvector + Langfuse v4, verified
live" for the real bugs that surfaced only once this path was actually exercised
end-to-end, and exactly how they were fixed.

**Dev/test mode (synthetic, fictional players)**: set `DATA_SOURCE=synthetic` before
`python -m pipeline.run_all` — faster (no 241MB download), and what the whole test
suite runs against, on either backend. The app refuses to hide this from you:
`/health` reports `data_source: "synthetic"` and every screen shows a persistent
"DEMO DATA" banner whenever the seeded database isn't real (`docs/DECISIONS.md`
"Synthetic data is no longer the silent default"). The API also refuses to start
at all against a database the pipeline has never been run against, rather than
silently serving empty tables.

Tests/evals need the dev+eval extras too: `pip install -e ".[dev,eval]"` (on
Windows without a C++ build toolchain, `ragas` — one of the `eval` extra's own
dependencies — fails to build; see `docs/DECISIONS.md` "RAGAS could not be
installed in this environment." `make setup` above deliberately skips this
extra so getting the app running never depends on it). Tests: `make test` (149
passing — see below). Lint/typecheck: `make lint && make typecheck`. Frontend
typecheck: `cd frontend && npx tsc --noEmit`.

## Game rules

| Rule | Value |
|---|---|
| Modes | World Cup (opponent = a national team's WC 2026 squad), Champions League (opponent = a club's UCL squad) |
| Opponent | Assigned by a draw; you don't choose |
| Player pool | Every player in the database **except** the opponent's squad |
| Budget | €1B, fixed for every match |
| Nationality limit | Max 3 players from the same country |
| Lineup | 11 players in one supported formation (4-3-3, 4-4-2, 4-2-3-1, 3-5-2, 3-4-3, 5-3-2) |
| Opponent counter | Opponent responds using only its real squad; max 3 counter rounds |
| World Cup knockout | Single match → extra time → penalties |
| Champions League knockout | Two legs; aggregate score → extra time → penalties in the second leg |
| Prices | Frozen per tournament snapshot |

Edge case (decided): players of the opponent's nationality who are **not** in the
opponent's squad are eligible, subject to the 3-per-country limit.

## Evaluation results

Real, measured numbers only — nothing here is an estimate. Where a result depends on
a golden set the project owner hasn't filled in yet, or a live LLM run nobody has
executed, it says so plainly instead of guessing.

| Metric | Result | Target (`docs/DESIGN.md` §12) |
|---|---|---|
| Backend test suite | **149 passed**, 0 failed | — |
| Numeric validator pass rate (coach report) | **100%** (10/10 samples), 0 fallbacks | 100% after fallback |
| Numeric validator pass rate (match report) | **100%** (10/10 samples), 0 fallbacks | 100% after fallback |
| DeepEval numeric faithfulness metric | **1.0 / 1.0** (coach / match) | — |
| Faithfulness (RAGAS, stub provider) | **1.0 / 1.0** — faithful by construction (`StubProvider` restyles nothing) | ≥ 0.90 |
| Faithfulness (RAGAS, live Anthropic provider) | **TODO: pending a live LLM run** (`LLM_PROVIDER=anthropic`, by the project owner) | ≥ 0.90 |
| Retrieval eval (Recall@10 / MRR / nDCG) | **TODO: pending `evals/golden/retrieval_queries.jsonl`** — ships with 2 labelled example rows only; CLAUDE.md reserves writing real cases for a human | Hybrid+rerank ≥ best single method |
| Embedding-model benchmark | **TODO: pending the same golden set** (`evals/embedding_benchmark.py` needs it for Recall@10) | — |
| Rating v2 vs. v1 backtest | **v2 does not beat v1** — correlation with actual goal margin 0.3409 vs. 0.3311 (v2 ahead), Brier score 0.2364 vs. 0.2284 (v2 behind); full numbers and method in `docs/DECISIONS.md` "Rating v2" | beats v1 on both axes |
| Pricing model MAE (real data, held out) | **€3.17M**, 35.7% of mean real market value | documented |
| Ability-score distribution (real data) | **4.1–96.5** (mean 49.6) — not collapsed to a constant | — (sanity check) |
| Budget sanity check (real data, €1B) | A full top-ability XI of the 95 "elite" players **does fit** under €1B; ~20 elite players are affordable alongside 8 median starters | documented |
| Real-data coverage | 4,755 players, 490 clubs, 48 national teams, 2,595 squad rows | — |

Pricing MAE and the ability-score range are measured against the real Transfermarkt
dataset (`DATA_SOURCE=real`, the default); the budget sanity check updated from an
earlier measurement in `docs/PROGRESS.md` once run fresh against the current dataset
snapshot — re-run `make setup && python -c "..."` (or just read the pipeline's own
printed report from `python -m pipeline.run_all`) if you want to reproduce it
yourself. CI runs the numeric/faithfulness eval subset on every push against
synthetic data (no 241MB download in CI); the nightly workflow adds the embedding
benchmark and a faithfulness gate that activates once a live-run baseline is
committed. See `docs/PROGRESS.md` Part 4 for exactly what each CI job checks and how
to demonstrate a failing gate yourself.

## Real data

The pipeline defaults to the real, public
[dcaribou/transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets)
export (CC0) — real players, real nationalities, real market values, real
WC2026/UCL2025-26 squads and minutes/goals/assists. `make setup` fetches it
automatically (241MB, once, into `data_raw/`, gitignored). `xg`/`xa` and a handful of
advanced per-90s are still approximated, since this export has no shot-quality data —
see `pipeline/real_source.py`'s docstring and `docs/PROGRESS.md` Phase 8 for exactly
what's real and what's derived. `DATA_SOURCE=synthetic` switches to the fictional
generator instead (dev/test only — see "How to run it" above).

## Observability

Every LLM call, retrieval, rerank, SQL-tool call, and `graph/nodes.py` node
(including the `analyse`/`opponent_counter`/`simulate` engine steps) is wrapped in a
[Langfuse](https://langfuse.com) trace by `observability.py` — a single module every
instrumented call site shares. It's a true no-op without
`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` set (true in CI and by default: this
project has no deployment to put real keys into), so tracing never needs a secret and
never blocks anything.

**To view a trace**: set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and
`LANGFUSE_HOST` in `.env` (self-hosted Langfuse via `docker compose up -d` — see
"How to run it" above for the exact dev keys this `docker-compose.yml` auto-
provisions, or [Langfuse Cloud](https://cloud.langfuse.com)'s free tier), then run
a normal session (`make api` + `make web`, or `make eval`). Every graph node shows
up as its own `node.<name>` trace in the Langfuse UI, tagged with the game
session's `session_id` — any LLM generation, retrieval, rerank, or SQL-tool call
made while handling that node nests underneath it automatically. Running
`evals/numeric_eval.py` or `evals/faithfulness_eval.py` attaches that sample's
score (`numeric_faithfulness_*`, `ragas_faithfulness_*`) directly onto the trace
its report was narrated in.

**Verified against a real, running Langfuse instance** (not just a fake client in
tests): `node.draw`, `node.validate`, `node.analyse`, `node.narrate_report`,
`node.opponent_counter`, `node.simulate`, `node.narrate_match`, `node.chat` all
appeared as real traces from a real Playwright session, with `llm.narrate`
(`GENERATION`) and `rag.retrieve` (`RETRIEVER`) nested underneath the nodes that
triggered them — see `docs/DECISIONS.md` for the two real bugs this surfaced
(`observability.py` was never actually passing its settings to the SDK, and the
first trace after a cold server start added enough latency to flake a 5s-timeout
Playwright assertion) and how they were fixed.

## Key design decisions (full detail in [`docs/DECISIONS.md`](docs/DECISIONS.md))

- **Real data by default**; synthetic Transfermarkt/Understat data (two
  deliberately-disagreeing record sets so `pipeline/id_resolution.py` does real
  fuzzy-matching work instead of a no-op) is an explicit `DATA_SOURCE=synthetic`
  opt-in, used by the test suite and CI — never the production default.
- **SQLite fallback** behind the same `VectorType`/`DATABASE_URL` the Postgres path
  uses, because there was no live Postgres to develop against in this environment.
- **LangGraph + `MemorySaver`**, not the Postgres checkpointer — sessions don't
  survive a server restart (hit for real during a browser playthrough, not just
  theorized).
- **Rating v2 was built and backtested, and did not beat v1** — the live default
  stays v1; v2 is fully implemented behind the same `RatingModel` interface.
- **`StubProvider`** is a real, deterministic, fully-tested LLM provider (its
  "narration" is the already-complete template, verbatim) — not a mock standing in
  for untested code. Set `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` for a real
  model.
- **Plain CSS, not Tailwind**, in the frontend — time budget; see `docs/DECISIONS.md`.
- **Langfuse tracing built from scratch in this build** (Part 5) — every LLM call,
  retrieval, rerank, SQL-tool call, and graph node, with session_id propagated from
  one root span per node rather than repeated on every leaf.

## Out of scope

- **Auth** — no user accounts, no login; a session is just a `session_id` in
  LangGraph's in-memory checkpointer.
- **Deployment** — `docker-compose.prod.yml` and the GitHub Actions workflows are
  fully authored but never run; no live deployment exists, by instruction.
- **Share links** — "copy result" and "download result image" are local only (text
  to the clipboard, a canvas-drawn PNG); there's no server-generated, persistent
  shareable URL for a match result.
- **Multiplayer** — the opponent is always a real squad driven by the engine, never
  another human player.
- **Live data updates** — prices and squads are frozen per tournament snapshot, not
  a continuously-refreshed feed; `weekly-pipeline.yml` is authored for a future
  production refresh but has never been run (no production database/secret exists).
