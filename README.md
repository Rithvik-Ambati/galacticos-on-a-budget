# Lineup Lab

Build an XI to beat an assigned real-world opponent. Get coach-style feedback on
weaknesses, rule-respecting swap suggestions, an overall rating, an opponent that
fights back, and a simulated match.

Full spec: [`docs/DESIGN.md`](docs/DESIGN.md). Build log, every bug found and fixed,
and the reasoning behind every non-obvious choice: [`docs/PROGRESS.md`](docs/PROGRESS.md)
and [`docs/DECISIONS.md`](docs/DECISIONS.md) — read those before this file if you want
the real story; this one is the summary.

**Core principle: the engine decides, the LLM explains.** Every number shown to the
user is produced by deterministic, tested code or a validated model. The LLM only
narrates engine output, answers follow-up questions using retrieved context, and
translates questions into read-only SQL.

## Architecture

```
React frontend (Vite + TS)
      │
FastAPI backend  ── Redis (cache)
      │
LangGraph orchestrator (game state, loops, interrupts, checkpointing)
      │
 ┌────┴──────────────┬──────────────────┐
Analysis engine     Hybrid RAG          LLM
(rules, rating,     (BM25 + vector,     (feedback, chat,
 swaps, counter,     RRF, rerank)        text-to-SQL)
 simulation)
 └────────┬──────────┘
   Postgres + pgvector  (stats, squads, prices, documents, vectors, sessions)
          ▲
   Weekly data pipeline (ingest → features → models → prices → documents → embeddings)

Cross-cutting: Langfuse tracing · pytest · GitHub Actions eval gates · Docker
```

Repo layout mirrors this: `pipeline/` → `engine/` → `rag/` + `llm/` → `graph/` → `api/`
→ `frontend/`, plus `db/` (models + migrations), `config/` (every tunable number),
`evals/` and `tests/`. `CLAUDE.md` is the standing rulebook Claude Code read on every
phase of this build — the single most load-bearing file in the repo if you want to
understand *why* things are shaped the way they are.

## How to run it

**This sandbox could not reach a live Postgres** (Docker Desktop's engine wouldn't
start — no WSL2/Hyper-V backend available; see `docs/DECISIONS.md`), so everything
below is the path actually exercised in this build. The Postgres/Docker path is fully
written (`docker-compose.yml`, the Alembic migration, `docker-compose.prod.yml`) but
untested live.

```bash
# backend — uses SQLite by default (config/settings.py); no Docker needed
pip install -e ".[dev,eval]"
python -m pipeline.download_real_data   # fetches the real dataset into data_raw/ (241MB, once)
python -m pipeline.run_all              # seeds dev.db -- DATA_SOURCE defaults to "real"
uvicorn api.main:app --reload --port 8000

# frontend, in a second shell
cd frontend
npm install
npm run dev                        # http://localhost:5173, proxies /api to :8000
```

**Dev/test mode (synthetic, fictional players)**: set `DATA_SOURCE=synthetic`
before `pipeline.run_all` — faster (no 241MB download), and what the whole test
suite runs against. The app refuses to hide this from you: `/health` reports
`data_source: "synthetic"` and every screen shows a persistent "DEMO DATA" banner
whenever the seeded database isn't real (`docs/DECISIONS.md` "Synthetic data is no
longer the silent default"). The API also refuses to start at all against a
database the pipeline has never been run against, rather than silently serving
empty tables.

With a real Postgres available: set `DATABASE_URL` in `.env` (see `.env.example`),
`make up && make migrate` instead of letting SQLite auto-create tables, then the same
`make pipeline && make api && make web`.

Tests: `pytest` (69 passing — see below). Lint/typecheck: `ruff check . && mypy engine
rag llm` (strict) `&& mypy pipeline graph db config api evals`. Frontend typecheck:
`cd frontend && npx tsc --noEmit`.

## Eval results

Real numbers, measured against the synthetic dataset this build seeds (`python -m
evals.run_all`, output in `evals/reports/baseline.json`):

| Metric | Result | Target (DESIGN.md §12) |
|---|---|---|
| Coach-report numeric validator pass rate | **100%** (10/10 samples) | 100% after fallback |
| Match-report numeric validator pass rate | **100%** (10/10 samples) | 100% after fallback |
| Validator fallback triggers | **0** | report pre-fallback rate |
| Pricing model MAE (held-out) | **~€11.0M**, 40.4% of mean price | documented |
| Ability-score vs. ground-truth correlation | **0.84** overall (0.78–0.88 per position group) | — (sanity check) |
| Budget sanity check | Budget raised to €1B (from €500M). A full top-2%-ability XI still does **not** fit; ~5 elite players now afford alongside 8 median starters (was ~2 at €500M) | "~3 elite + 8 good" (pre-raise target) |
| Test suite | **69 passed**, 0 failed | — |
| Retrieval eval (Recall@10 / MRR / nDCG) | **not run** — `evals/golden/retrieval.jsonl` is an empty template; CLAUDE.md requires a human to write it | Hybrid+rerank ≥ best single method |
| Faithfulness (RAGAS) | **not run** — needs the same human-written golden chat set | ≥ 0.90 |
| Rating v2 vs. v1 backtest | **not attempted** — needs real historical match results; this build has no event-level data source (see DECISIONS.md) | beats v1 baseline |

The MAE and correlation numbers above come from `pipeline.pricing`/`pipeline.features`
running against the synthetic world in `pipeline/synthetic_source.py` (the default) —
read `docs/DECISIONS.md` before citing them as anything other than "the pipeline code
works and produces sane numbers on fake data." The same pipeline run against real data
(`DATA_SOURCE=real`, see above) gets a pricing MAE of ~€3.33M (40.7% of mean real
market value, in line with the synthetic number) and ability scores spanning 4.1-96.5
(not collapsed) — full numbers in `docs/PROGRESS.md` Phase 8.

## Real data

The pipeline defaults to the real, public
[dcaribou/transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets)
export (CC0) — real players, real nationalities, real market values, real
WC2026/UCL2025-26 squads and minutes/goals/assists. Run
`python -m pipeline.download_real_data` once first (fetches a 241MB zip into
`data_raw/`, gitignored). `xg`/`xa` and a handful of advanced per-90s are still
approximated, since this export has no shot-quality data — see
`pipeline/real_source.py`'s docstring and `docs/PROGRESS.md` Phase 8 for exactly
what's real and what's derived. `DATA_SOURCE=synthetic` switches to the fictional
generator instead (dev/test only — see "How to run it" above).

## Observability

Every LLM call, retrieval, rerank, SQL-tool call, and `graph/nodes.py` node
(including the `analyse`/`opponent_counter`/`simulate` engine steps) is wrapped
in a [Langfuse](https://langfuse.com) trace by `observability.py` — a single
module every instrumented call site shares. It's a true no-op without
`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` set (true in CI and by default:
this project has no deployment to put real keys into), so tracing never needs a
secret and never blocks anything.

**To view a trace**: set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and
`LANGFUSE_HOST` in `.env` (self-hosted Langfuse via `docker compose up -d`, or
[Langfuse Cloud](https://cloud.langfuse.com)'s free tier), then run a normal
session (`make api` + `make web`, or `make eval`). Every graph node shows up as
its own `node.<name>` trace in the Langfuse UI, tagged with the game session's
`session_id` — any LLM generation, retrieval, rerank, or SQL-tool call made
while handling that node nests underneath it automatically. Running
`evals/numeric_eval.py` or `evals/faithfulness_eval.py` attaches that sample's
score (`numeric_faithfulness_*`, `ragas_faithfulness_*`) directly onto the trace
its report was narrated in.

## Key design decisions (full detail in `docs/DECISIONS.md`)

- **Real data by default**; synthetic Transfermarkt/Understat data (two
  deliberately-disagreeing record sets so `pipeline/id_resolution.py` does real
  fuzzy-matching work instead of a no-op) is an explicit `DATA_SOURCE=synthetic`
  opt-in, used by the test suite and CI (never the production default — see
  `docs/DECISIONS.md` "Synthetic data is no longer the silent default").
- **SQLite fallback** behind the same `VectorType`/`DATABASE_URL` the Postgres path
  uses, because there was no live Postgres to develop against.
- **LangGraph + `MemorySaver`**, not the Postgres checkpointer — sessions don't
  survive a server restart (hit for real during Phase 6's browser playthrough, not
  just theorized).
- **Rating v1 and its expected-goals formula** are explicit placeholders for Phase
  7's never-attempted rating v2 (needs historical match data this build doesn't have).
- **`StubProvider`** is a real, deterministic, fully-tested LLM provider (its
  "narration" is the already-complete template, verbatim) — not a mock standing in
  for untested code. Set `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` for a real
  model.
- **Plain CSS, not Tailwind**, in the frontend — time budget; see DECISIONS.md.

## What's not done

- The two human-written golden sets (`evals/golden/retrieval.jsonl`,
  `evals/golden/chat.jsonl`) — the runners are built and tested against them being
  empty; CLAUDE.md reserves actually writing them for a human.
- Rating v2, and therefore the v1-vs-v2 backtest.
- Anything in `docker-compose.prod.yml` or the GitHub Actions workflows has been
  authored but never run — no deployment was done in this build, by instruction.
