.PHONY: up down migrate pipeline test eval api web lint typecheck

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

eval:
	python -m evals.run_all

api:
	uvicorn api.main:app --reload --port 8000

web:
	cd frontend && npm run dev

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy engine rag llm
