# Gaffer — System Design Document

> Build an XI to beat a real opponent. Get coached, get countered, play it out.

**Core principle: the engine decides, the LLM explains.** Every number shown to the user is produced by deterministic, tested code or a validated model. The LLM only narrates engine output, answers follow-up questions using retrieved context, and translates questions into read-only SQL.

---

## 1. Game rules

| Rule | Value |
|---|---|
| Modes | World Cup (opponent = a national team's WC 2026 squad), Champions League (opponent = a club's UCL squad) |
| Opponent | Assigned by a draw; the user does not choose |
| Player pool | Every player in the database **except** the opponent's squad |
| Budget | €1B, fixed for every match (raised from the original €500M — see docs/DECISIONS.md) |
| Nationality limit | Max 3 players from the same country |
| Lineup | 11 players in one supported formation (4-3-3, 4-4-2, 4-2-3-1, 3-5-2, 3-4-3, 5-3-2) |
| Opponent counter | Opponent responds using only its real squad; max 3 counter rounds |
| World Cup knockout | Single match → extra time → penalties |
| Champions League knockout | Two legs; aggregate score → extra time → penalties in the second leg |
| Prices | Frozen per tournament snapshot |

Edge case (decided): players of the opponent's nationality who are **not** in the opponent's squad are eligible, subject to the 3-per-country limit.

---

## 2. User journey

1. **Welcome** — choose World Cup or Champions League; sign in or play as guest.
2. **Draw** — animated draw reveals the opponent.
3. **Scouting report** — likely lineup, playing style, danger men, weak points.
4. **Build XI** — pick formation, fill 11 slots from a searchable pool. Top bar shows budget left, nationality counts, live rating. Ineligible players are greyed out with the reason.
5. **Coach's report** — rating /100, win/draw/loss %, strengths, weaknesses (highlighted as red zones on the pitch), one-tap swap suggestions, budget-efficiency tip.
6. **Opponent responds** — opponent's counter move, updated rating, moved red zones. User chooses Counter (up to 3 rounds) or Lock in.
7. **Match day** — animated event timeline and final score (extra time / penalties / two legs as per mode).
8. **Match report** — key moments, man of the match, what worked, manager score (% of best possible lineup), chat box, replay / new opponent / share.

---

## 3. Architecture

```
React frontend
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

Cross-cutting: Langfuse tracing · pytest + DeepEval · GitHub Actions eval gates · Docker
```

---

## 4. Tech stack and justifications

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+, SQL | Engine, ML and backend in one language; stats logic in SQL |
| Database | PostgreSQL 16 + pgvector >= 0.8 | Vectors live next to stats, so similarity search and business filters (budget, nationality, exclusion) run in one SQL query and one transaction. pgvector 0.8 iterative index scans handle restrictive filters with HNSW |
| Vector DB alternatives | Pinecone / Qdrant / Weaviate — **not used** | ~40k players; a second datastore adds cost and sync risk with no benefit. Revisit only at 10^8+ vectors |
| Lexical search | `rank_bm25` (in-process) | True BM25; Postgres `ts_rank` is not BM25. Corpus is small enough to hold in memory |
| Embeddings | `BAAI/bge-small-en-v1.5` (baseline) | Final choice decided by benchmark on our golden set vs `bge-base` and `e5-base` (recall vs latency) |
| Reranker | `BAAI/bge-reranker-base` (cross-encoder) | Precision on top-50 candidates |
| Orchestration | LangGraph | The flow has loops (counter rounds), branching (chat routing), human-in-the-loop (counter / lock in) and persistence |
| LangChain | Minimal (model + tool wrappers used by LangGraph) | Avoid heavy chain abstractions |
| LlamaIndex | **Not used** | Overlaps with LangGraph + pgvector |
| LLM | One API model behind a provider interface (configurable) | Swappable; used only for narration, chat, text-to-SQL |
| ML | scikit-learn, XGBoost, SHAP, SciPy, OR-Tools | Pricing, rating model, explanations, simulation, optimal-lineup solver |
| Backend | FastAPI, async SQLAlchemy, Pydantic v2 | Typed contracts, streaming |
| Cache | Redis | Repeat scouting reports and analyses |
| Frontend | React + Vite + TypeScript + Tailwind, TanStack Query | Pitch builder UI |
| Evaluation | RAGAS, DeepEval, pytest | Retrieval quality, faithfulness, numeric correctness |
| Observability | Langfuse (self-hosted) | Traces, cost, latency, prompt versions, eval scores |
| Delivery | Docker Compose, GitHub Actions, Cloud Run or ECS + managed Postgres | Reproducible, gated deploys |

---

## 5. Data sources

| Source | Used for | Notes |
|---|---|---|
| Transfermarkt Datasets (dcaribou, Kaggle / GitHub, CC0) | Players, clubs, national teams, WC 2026 squads and games, lineups, appearances, market valuations | Refreshed weekly. Primary backbone and ID space |
| Understat | xG, xA, shots, key passes for top leagues | Detailed stats for top leagues only |
| StatsBomb Open Data | Event data for selected competitions | Matchup research and model validation |
| FBref (optional) | Advanced per-90 stats | Check terms before scraping; do not depend on it |

**Coverage risk:** detailed stats exist mainly for top leagues. Players outside coverage get an ability score from Transfermarkt appearance data (minutes, goals, assists, cards, team strength) and a `confidence` flag shown in the UI.

**Entity resolution:** `player_id_map(tm_id, understat_id, statsbomb_id, match_method, match_score)`. Match on normalised name + date of birth + club; fuzzy matching only above a threshold; unresolved cases logged for manual review.

---

## 6. Data model (core tables)

| Table | Key columns |
|---|---|
| `players` | `player_id`, name, dob, nationality, positions, preferred_foot, height, current_club_id |
| `player_id_map` | see above |
| `clubs`, `national_teams` | id, name, country, competition |
| `squads` | `squad_id`, team_id, team_type (club/national), tournament (`WC2026`/`UCL2026`), player_id |
| `player_stats_season` | player_id, season, competition, minutes, per-90 metrics, xG, xA |
| `player_features` | player_id, snapshot, role_percentiles (jsonb), style_vector `vector(n)`, ability_score, confidence |
| `prices` | player_id, tournament_snapshot, price_eur, market_value_eur, ability_value_eur |
| `team_profiles` | team_id, snapshot, attack_channels, ppda, crosses_per_match, set_piece_threat, aerial, danger_players (jsonb) |
| `documents` | doc_id, doc_type (player_profile / opponent_report / match_report), entity_id, text, metadata (jsonb), embedding `vector(384)`, content_hash, embed_model |
| `game_sessions` | session_id, user_id, mode, opponent_id, state (jsonb), created_at |
| `eval_runs` | run_id, git_sha, metrics (jsonb), passed |

Indexes: HNSW on `documents.embedding` (cosine), btree on metadata fields used in filters, GIN on jsonb metadata.

---

## 7. Models and engine logic

### 7.1 Ability score (0–100)
Position-specific weighted percentiles of recent per-90 stats (last 2 seasons, recency-weighted, minimum minutes threshold), adjusted by league strength coefficient. Output also includes role-fit scores per role template (e.g. ball-playing CB, inverted FB, ball-winning DM, inside forward).

### 7.2 Pricing (de-biased)
1. Train XGBoost: `log(market_value) ~ ability, age, league, club_strength, position, minutes`.
2. Predict each player's value with **age set to the population mean** and club strength neutralised → `ability_value`.
3. `price = 0.7 × ability_value + 0.3 × market_value`, rounded to €1M, floor €1M.
4. Budget sanity check: the budget (config/game.py's `BUDGET_EUR`) should afford ~3 elite players + 8 good players, not a full superstar XI. Tune the curve if a full superstar XI fits.

Metrics: MAE on held-out market values; audit top-50 most expensive list by hand.

### 7.3 Rating
- **v1 (MVP):** weighted sub-ratings → overall /100. Sub-ratings: attack, midfield control, defence, matchup, cohesion, balance.
- **v2 (target):** XGBoost trained on historical matches. Features: aggregated lineup vectors for both sides (per zone). Target: xG difference. Rating = calibrated transform of predicted xG margin vs this opponent. SHAP gives per-player and per-zone contributions.
- Validation: backtest on held-out matches; report correlation with actual xG margin and Brier score of derived win probabilities.

### 7.4 Matchups and weaknesses
Pitch split into zones (left/centre/right × defence/midfield/attack). For each opponent threat, map to the user's player(s) defending that zone and compute a mismatch score (e.g. opponent take-ons & progressive carries vs defender tackles won & dribbled-past rate). Rule catalogue (each with severity 0–1 and evidence stats):
- zone mismatch above threshold
- missing role (e.g. no ball-winner vs possession team)
- aerial deficit vs high-cross team
- low press resistance vs high-press team
- set-piece vulnerability
- out-of-position player, footedness imbalance, low-confidence player
- budget misallocation (spend share by unit vs threat share by zone)

### 7.5 Swap optimizer
For each weakness (by severity): candidates = eligible players for that position where `price <= outgoing_price + budget_left` and nationality limit holds after removal. Re-score the **full** lineup for each candidate. Return top 3 by rating gain, plus budget-freeing swaps (similar rating, lower price). Never suggest a rule-breaking swap.

### 7.6 Manager score
Optimal lineup found with OR-Tools (ILP): maximise sum of role-fit values subject to formation, budget and nationality constraints; re-score the top-k solutions with the full rating model. Manager score = user rating ÷ best found rating.

### 7.7 Opponent counter (best response)
Move set: substitute a starter with a squad player, reposition a player, or change formation (from a small allowed set). Greedy/beam search (beam width 5, max 2 changes per round) minimising the user's predicted xG margin. Max 3 rounds per match. Deterministic given the same inputs (fixed seed).

### 7.8 Match simulation
Poisson goals with λ from predicted xG for each side; 10,000 Monte Carlo runs → W/D/L %, scoreline distribution, chance share by zone. Extra time: λ × (30/90) × stamina factor. Penalties: per-taker conversion probabilities from history (fallback league average). UCL: two legs with home advantage adjustment, aggregate then ET/penalties. A single "narrative" run is sampled for the Match Day timeline.

---

## 8. RAG design

**Documents (entity-centric, templated from stats):**
- Player profile per player-season (role, strengths, weaknesses, key per-90s, style summary)
- Opponent tactical report per team
- Match reports (only long docs; split by section with ~15% overlap)

Metadata on every chunk: `entity_id, doc_type, position, nationality, price, season, team_id`.

**Retrieval pipeline:** query → (optional rewrite) → BM25 top-50 + dense top-50 (with SQL metadata filters) → Reciprocal Rank Fusion (k=60) → cross-encoder rerank → top-5.

**Low-relevance handling:** if top rerank score < threshold → rewrite and retry once → else route to SQL tool or answer "not enough data". Irrelevant context is never passed to the LLM; such cases are logged in Langfuse.

---

## 9. LLM usage and guardrails

1. **Coach feedback / match report:** input is engine JSON + retrieved context. The LLM writes prose with placeholders (`{rating}`, `{swap_1_gain}`), code fills values.
2. **Numeric validator:** extract all numbers from final text; each must match an engine value (with rounding tolerance). On failure: regenerate once, then fall back to a template.
3. **Chat:** tool-calling agent with tools `query_stats`, `retrieve`, `evaluate_swap`, `simulate`, `similar_players`.
4. **Text-to-SQL safety:** read-only DB role, table allowlist, statement timeout (2s), row limit, SELECT-only parser check.
5. Prompts versioned in Langfuse.

---

## 10. LangGraph design

**State:** `mode, session_id, opponent_id, formation, lineup, budget_left, nationality_counts, analysis, counter_round, counter_history, simulation, messages`.

**Nodes:** `draw → scout → build (interrupt) → validate → analyse → narrate_report → user_decision (interrupt) → opponent_counter → [loop to build or analyse] → simulate → narrate_match → chat`.

**Edges:** conditional on `user_decision` (counter / lock_in) and `counter_round < 3`. Checkpointer: Postgres saver keyed by `session_id`.

---

## 11. API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/sessions` | Create session with mode → returns session_id |
| POST | `/sessions/{id}/draw` | Assign opponent |
| GET | `/sessions/{id}/scout` | Scouting report |
| GET | `/players/search` | Eligible players (position, name, price range) with ineligibility reasons |
| POST | `/sessions/{id}/lineup/validate` | Rule check + live rating |
| POST | `/sessions/{id}/lineup/analyse` | Full coach report |
| POST | `/sessions/{id}/counter` | Opponent response |
| POST | `/sessions/{id}/decision` | counter / lock_in |
| POST | `/sessions/{id}/simulate` | Match simulation + report |
| POST | `/sessions/{id}/chat` | Streamed chat (SSE) |
| GET | `/health` | Liveness / readiness |

All request/response bodies are Pydantic models; errors use a consistent problem-details schema.

---

## 12. Evaluation plan

| Area | Method | Target (initial) |
|---|---|---|
| Retrieval | Golden set (~100 queries, hand-labelled) — Recall@10, MRR, nDCG; ablation BM25 / dense / hybrid / hybrid+rerank | Hybrid+rerank >= best single method |
| Embedding model | Same golden set across 3 models + latency | Documented choice |
| Faithfulness | RAGAS faithfulness on chat answers | >= 0.90 |
| Numeric correctness | Validator pass rate on generated reports | 100% after fallback; report pre-fallback rate |
| Pricing model | MAE on held-out market values; hand audit | Documented |
| Rating model | Backtest correlation with xG margin; Brier score | Beats v1 weighted baseline |
| Rules | pytest property tests (budget, nationality, exclusion) | 100% |
| Latency | p95 per endpoint | analyse < 3s (excluding LLM stream) |

**CI gate:** on every PR, run unit tests + eval subset with pinned model version; fail if faithfulness < 0.90, Recall@10 drops > 2 points vs baseline in repo, or any numeric validation fails. Full eval runs nightly.

---

## 13. Repository structure

```
gaffer/
├── CLAUDE.md
├── docs/DESIGN.md, docs/PROGRESS.md, docs/DECISIONS.md
├── docker-compose.yml, .env.example, Makefile
├── pipeline/          # ingest, id_resolution, features, pricing, documents, embeddings
├── engine/            # rules, rating, matchups, weaknesses, swaps, optimizer, counter, simulation
├── rag/               # bm25, dense, fusion, rerank, retriever
├── llm/               # provider, prompts, narrator, validator, sql_tool
├── graph/             # state, nodes, graph
├── api/               # main, routers, schemas, deps
├── frontend/          # React app
├── evals/             # golden sets, retrieval_eval, faithfulness, numeric, backtests
├── tests/             # unit + integration
├── db/migrations/     # Alembic
└── .github/workflows/ # ci.yml, nightly-eval.yml
```

---

## 14. Build phases

| # | Phase | Done when |
|---|---|---|
| 1 | Data foundation | DB populated; ID resolution report; squads for WC 2026 and UCL load |
| 2 | Ability + pricing | Prices table; budget sanity check passes; top-50 audit |
| 3 | Engine core | Rules, rating v1, weaknesses, swaps, manager score with tests |
| 4 | Scenarios | Opponent counter, simulation, knockout formats with tests |
| 5 | AI layer | RAG, narrator, validator, chat, LangGraph flow |
| 6 | API + frontend | All 8 screens working end to end |
| 7 | Production | Evals, Langfuse, CI gates, Docker, deploy, rating v2 backtest |

MVP checkpoint = phases 1–3 + a minimal UI for World Cup mode.

---

## 15. Risks and open decisions

- **Stat coverage outside top leagues** → confidence flags; ability from appearance data.
- **UCL squad completeness** in source data → verify in phase 1; fallback to club squad as of snapshot date.
- **Price curve feel** → tune by playtesting; document final curve in DECISIONS.md.
- **LLM cost** → cache reports per (lineup hash, opponent, round).
- **Scraping terms** → do not depend on sources that forbid it.
