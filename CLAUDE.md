# CLAUDE.md — Gaffer

## What this project is
A football game: the user is assigned a real opponent (World Cup 2026 national squad or a UCL club squad), builds an XI from every other player in the world within €1B (raised from the original €500M) and max 3 players per nationality, and receives coach-style feedback (rating, weaknesses, swaps), an opponent counter-move, and a simulated match. Full spec: `docs/DESIGN.md`. Read it before starting any phase.

## Non-negotiable rules

1. The engine decides, the LLM explains. The LLM never computes, estimates or invents a number. All numbers come from `engine/` or `pipeline/`. LLM prose uses placeholders filled by code, and output passes `llm/validator.py`.
2. Game rules are enforced in one place: `engine/rules.py`. Every lineup, swap suggestion and optimizer result must pass it. Never duplicate rule logic elsewhere.
3. Never suggest or accept a rule-breaking lineup (budget, nationality limit, opponent-squad exclusion, formation validity).
4. Deterministic by default: seed all randomness (`SEED` in config). Same input → same output.
5. Text-to-SQL is read-only: use the `readonly` DB role, table allowlist, SELECT-only check, 2s timeout, row limit.
6. No secrets in code. Use `.env` (see `.env.example`).

## Stack (do not substitute without asking)
Python 3.11, FastAPI, Pydantic v2, async SQLAlchemy, Alembic, PostgreSQL 16 + pgvector >= 0.8, Redis, LangGraph (+ minimal LangChain wrappers), rank_bm25, sentence-transformers (bge models), XGBoost, scikit-learn, SHAP, SciPy, OR-Tools, RAGAS, DeepEval, Langfuse, pytest. Frontend: React + Vite + TypeScript + Tailwind + TanStack Query. Do not add: LlamaIndex, Pinecone, Qdrant, Weaviate, or any new major dependency without asking.

## Repo layout

```
pipeline/  engine/  rag/  llm/  graph/  api/  frontend/  evals/  tests/  db/migrations/  docs/
```

Keep modules small and single-purpose. Engine code must not import from `llm/` or `api/`.

## Conventions

* Type hints everywhere; `mypy --strict` must pass for `engine/`, `rag/`, `llm/`.
* Lint/format: `ruff check` and `ruff format`.
* Pydantic models for all API schemas and for engine outputs that cross module boundaries.
* Money stored as integer euros. Ratings as floats 0–100, rounded only at presentation.
* Docstrings on public functions: what it does, inputs, outputs, and which DESIGN.md section it implements.
* Config via `pydantic-settings`; no magic numbers in logic — put thresholds and weights in `config/`.

## Testing

* Every phase ships with tests. Rules and optimizer get property-based tests (`hypothesis`).
* Run before finishing any task: `make lint && make typecheck && make test`.
* Never delete or weaken a failing test to make it pass; fix the code or flag the test.
* Golden eval sets in `evals/golden/` are written by the human. Do not generate or edit expected answers.

## Commands

```
make up          # docker compose up (postgres, redis, langfuse)
make migrate     # alembic upgrade head
make pipeline    # run full data pipeline
make test        # pytest
make eval        # evaluation suite
make api         # run FastAPI locally
make web         # run frontend
```

## Workflow

* Work one phase at a time as instructed. Do not start the next phase unprompted.
* At the end of each task: update `docs/PROGRESS.md` (what was built, how to verify, known issues) and add any design decision with its reason to `docs/DECISIONS.md`.
* If the spec is ambiguous or data does not match assumptions, stop and ask rather than guessing. Report data-quality findings with counts.
* Prefer small, reviewable commits with clear messages (`feat(engine): add swap optimizer`).
