# Claude Code phase prompts — Lineup Lab

How to use: put `DESIGN.md` in `docs/` and `CLAUDE.md` in the repo root. Paste one prompt at a time. Do not move on until every acceptance check passes and you have done the manual checks yourself.

## Phase 1 — Data foundation

```
Read CLAUDE.md and docs/DESIGN.md (sections 5, 6, 13). Implement Phase 1: Data foundation.

Build:
1. Repo scaffold per DESIGN.md section 13: pyproject (uv or poetry), Makefile targets from CLAUDE.md, docker-compose with postgres (pgvector >= 0.8), redis, langfuse; .env.example; ruff, mypy, pytest config.
2. Alembic migrations for all tables in DESIGN.md section 6 (documents.embedding as vector(384), HNSW cosine index; readonly DB role).
3. pipeline/ingest: download and load the Transfermarkt Datasets (dcaribou) CSVs into staging tables; load Understat season stats for top leagues.
4. pipeline/id_resolution: build player_id_map using normalised name + date of birth + club; fuzzy match only above a configurable threshold; write unresolved cases to a review CSV.
5. Load squads: WC 2026 national squads and UCL club squads into `squads`, with tournament tags.
6. A data-quality report script printing: player counts, % with detailed stats, % with market value, squad sizes per team, unresolved ID count.

Acceptance:
- `make up && make migrate && make pipeline` runs from a clean clone.
- Tests for name normalisation, ID matching and squad loading pass.
- Data-quality report is generated and summarised in docs/PROGRESS.md.
Stop and report if WC 2026 or UCL squads are incomplete in the source data.
```

Your manual checks: open the DB and spot-check 10 famous players across both sources; check one full WC squad and one UCL squad against reality; read the unresolved-ID CSV.

## Phase 2 — Ability score and pricing

```
Read CLAUDE.md and docs/DESIGN.md (sections 7.1, 7.2). Implement Phase 2.

Build:
1. pipeline/features: per-90 metrics (last 2 seasons, recency-weighted, min-minutes threshold), position-relative percentiles, league strength coefficients, role-fit scores for the role templates, style vectors, confidence flag for low-coverage players.
2. Ability score 0–100 per player, with config-driven position weights.
3. pipeline/pricing: XGBoost on log(market_value) with features from DESIGN 7.2; compute ability_value with age set to population mean and club strength neutralised; price = 0.7*ability_value + 0.3*market_value, rounded to €1M, floor €1M; store per tournament snapshot.
4. Scripts: (a) pricing model MAE on a held-out split, (b) top-50 most expensive players, (c) budget sanity check — how many elite (top 2% ability) players fit in €500M alongside 8 median starters.
5. Add a notebook or markdown report in evals/ with the results.

Acceptance:
- Tests for per-90 calculation, percentile ranking and price formula pass.
- Budget sanity check prints results; if a full top-ability XI fits under €500M, report it and propose a curve adjustment rather than silently changing it.
```

Your manual checks: read the top-50 list — does it look like the real best players? Are young hyped players cheaper than before and in-form veterans fairly priced? Does €500M force real trade-offs?

## Phase 3 — Engine core

```
Read CLAUDE.md and docs/DESIGN.md (sections 1, 7.3–7.6). Implement Phase 3.

Build in engine/:
1. rules.py: validate lineup (11 players, formation slots, budget <= €500M, max 3 per nationality, opponent-squad exclusion). Return structured reasons for every violation. Also an `eligibility(player, current_lineup, session)` function returning eligible/ineligible with a reason, for the search endpoint.
2. team_profile.py: opponent profile from team_profiles (attack channels, press intensity, crosses, set pieces, danger players).
3. rating.py: rating v1 — sub-ratings (attack, midfield control, defence, matchup, cohesion, balance) and weighted overall 0–100; weights in config. Expose a RatingModel interface so v2 can replace it later.
4. matchups.py + weaknesses.py: zone mismatch scoring and the full rule catalogue in DESIGN 7.4; each weakness has type, zone, severity 0–1 and evidence stats.
5. swaps.py: swap optimizer per DESIGN 7.5 — full-lineup re-scoring, top 3 per weakness, plus budget-freeing swaps; every suggestion must pass rules.py.
6. optimizer.py: OR-Tools ILP for best lineup under constraints; manager score.
7. A CLI: `python -m engine.analyse --opponent <team> --lineup lineup.json` printing the full analysis JSON.

Acceptance:
- Property-based tests (hypothesis): no swap or optimizer output ever violates a rule.
- Unit tests for each weakness rule with hand-built fixtures.
- Analysis JSON schema is a Pydantic model and documented in docs/PROGRESS.md.
```

Your manual checks: build 3 lineups by hand vs Argentina (one strong, one with an obvious weak left back, one all-attack). Does the engine find the weaknesses you planted? Do the swaps make football sense?

## Phase 4 — Scenarios: opponent counter and simulation

```
Read CLAUDE.md and docs/DESIGN.md (sections 1, 7.7, 7.8). Implement Phase 4.

Build in engine/:
1. counter.py: opponent best response per DESIGN 7.7 (moves: substitute from squad, reposition, formation change; beam width 5; max 2 changes per round; max 3 rounds; deterministic with seed). Output: moves made, explanation fields (targeted zone, player involved), rating before/after.
2. simulation.py: Poisson Monte Carlo (10,000 runs) with λ from the rating model's predicted xG; W/D/L %, scoreline distribution, chance share by zone; one sampled narrative run with minute-by-minute events.
3. Formats: World Cup single match with ET (λ × 30/90 × stamina factor) and penalties (per-taker conversion, league-average fallback); UCL two legs with home advantage and aggregate → ET/penalties.
4. Extend the CLI with `--counter` and `--simulate`.

Acceptance:
- Tests: counter never uses a player outside the opponent's squad; round cap enforced; simulation probabilities sum to 1; same seed → identical output; knockout matches never end in a draw.
- Performance: counter round < 1s, simulation < 1s on a laptop.
```

Your manual checks: does the opponent's counter target the zone you'd expect? Do simulated win rates feel plausible (strong XI vs weak opponent should win clearly, not 95%+ every time)?

## Phase 5 — AI layer: RAG, narration, chat, LangGraph

```
Read CLAUDE.md and docs/DESIGN.md (sections 8, 9, 10). Implement Phase 5.

Build:
1. pipeline/documents + embeddings: templated player profiles and opponent reports from stats; content_hash-based incremental embedding with bge-small-en-v1.5; store embed_model.
2. rag/: BM25 (rank_bm25), dense search in pgvector with metadata filters, RRF fusion (k=60), cross-encoder rerank (bge-reranker-base), low-relevance threshold with one rewrite-and-retry, then fallback signal.
3. llm/provider.py: provider interface, model from env. llm/narrator.py: coach report and match report prose using placeholders filled by code. llm/validator.py: extract all numbers, check against engine output with rounding tolerance; regenerate once, then template fallback. llm/sql_tool.py: guarded text-to-SQL per CLAUDE.md rule 5.
4. graph/: LangGraph state, nodes and conditional edges per DESIGN 10; interrupts at build and user_decision; Postgres checkpointer.
5. Chat agent with tools: query_stats, retrieve, evaluate_swap, simulate, similar_players.
6. Langfuse tracing on every LLM call, retrieval and rerank step.
7. evals/: retrieval eval runner (Recall@10, MRR, nDCG, ablation across BM25/dense/hybrid/hybrid+rerank) and embedding benchmark runner. Leave golden set files as empty templates — I will write them.

Acceptance:
- Tests: validator catches an injected wrong number; SQL tool rejects non-SELECT and non-allowlisted tables; graph loop stops at 3 counter rounds.
- A full session can be run from a Python script end to end.
```

Your manual checks: write the golden sets yourself (~100 retrieval queries, ~30 chat questions). Read 10 generated coach reports — do they sound like a coach and match the engine numbers?

## Phase 6 — API and frontend

```
Read CLAUDE.md and docs/DESIGN.md (sections 2, 11). Implement Phase 6.

Build:
1. api/: all endpoints in DESIGN 11 with Pydantic schemas, problem-details errors, Redis caching of scout and analyse results keyed by (opponent, lineup hash, round), SSE streaming for chat, /health.
2. frontend/: the 8 screens in DESIGN 2 — welcome/mode select, draw animation, scouting report, build XI (formation picker, pitch with slots, player search with eligibility reasons, top bar with budget / nationality counts / live rating), coach's report with red zones and one-tap swaps, opponent response with Counter / Lock in, match day timeline, match report with chat.
3. Responsive layout (mobile and desktop), loading and error states on every screen.
4. Playwright end-to-end test: complete one World Cup match and one UCL two-legged tie.

Acceptance:
- `make api` + `make web` gives a fully playable game.
- E2E tests pass.
```

Your manual checks: play 5 full matches yourself on desktop and phone. Note anything confusing and fix it before phase 7.

## Phase 7 — Production: evals, CI, deploy, rating v2

```
Read CLAUDE.md and docs/DESIGN.md (sections 7.3, 12, 14). Implement Phase 7.

Build:
1. evals/: faithfulness (RAGAS), numeric correctness (DeepEval custom metric using the validator), retrieval metrics — all reading the golden sets I wrote. Store results in eval_runs and a baseline JSON in the repo.
2. .github/workflows/ci.yml: lint, typecheck, tests, eval subset with pinned model; fail on thresholds in DESIGN 12. nightly-eval.yml: full eval suite.
3. Rating v2: XGBoost on historical matches (lineup zone features for both sides → xG difference), calibration, SHAP explanations, backtest vs v1 (correlation with xG margin, Brier score). Swap in via the RatingModel interface only if it beats v1; write the comparison to evals/reports/.
4. Production Dockerfiles, docker-compose.prod.yml, deploy config for Cloud Run (or ECS), managed Postgres migration steps, scheduled weekly pipeline job.
5. README: architecture diagram, how to run, eval results table, key design decisions.

Acceptance:
- A PR that breaks faithfulness or a numeric check fails CI (demonstrate with a throwaway branch).
- Deployed URL works end to end.
- README contains real measured numbers.
```

Your manual checks: read the v1 vs v2 backtest yourself; take screenshots of a failing and passing CI gate and a Langfuse trace for your portfolio.
