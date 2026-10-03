.PHONY: up down migrate pipeline test eval eval-retrieval eval-embeddings eval-faithfulness eval-numeric eval-live api web lint typecheck

up:
	docker compose up -d

down:
	docker compose down

migrate:
	alembic -c db/alembic.ini upgrade head

pipeline:
	python -m pipeline.run_all

test:
	pytest

# Runs everything except eval-live (docs/DESIGN.md section 12 / CLAUDE.md: live LLM
# runs never execute in CI or by default -- LLM_PROVIDER=anthropic opts in by hand).
# evals/run_all.py itself calls numeric + retrieval + faithfulness; embedding_benchmark
# is a separate model-selection tool, not part of the CI gate, so it's run here too but
# not inside run_all.py.
eval:
	python -m evals.run_all
	python -m evals.embedding_benchmark

eval-retrieval:
	python -m evals.retrieval_eval

eval-embeddings:
	python -m evals.embedding_benchmark

eval-faithfulness:
	python -m evals.faithfulness_eval

eval-numeric:
	python -m evals.numeric_eval

eval-live:
	python -m evals.live_llm_test

api:
	uvicorn api.main:app --reload --port 8000

web:
	cd frontend && npm run dev

lint:
	ruff check .

typecheck:
	mypy engine rag llm pipeline db config api evals graph observability.py
