# Production image: the real app -- Postgres + pgvector, real Transfermarkt data,
# the real Anthropic-backed chat agent. Distinct from Dockerfile.demo (synthetic
# data, SQLite, stub LLM, zero external services) -- see that file's own header.
# This image expects DATABASE_URL (a real Postgres with pgvector reachable at
# startup; migration 0001 creates the extension itself), ANTHROPIC_API_KEY and
# LLM_PROVIDER=anthropic, and DATA_SOURCE=real -- see render.yaml / docs/DECISIONS.md
# "Real pgvector production deployment" for how those get set. The real data
# pipeline (pipeline.run_all) is deliberately NOT run at build or container-start
# time -- it needs network access to the dataset and takes minutes; it's run once
# against the target database from a real seeding step instead, same as any other
# one-time database seed.

FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim AS base

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY config ./config
COPY db ./db
COPY engine ./engine
COPY pipeline ./pipeline
COPY rag ./rag
COPY llm ./llm
COPY graph ./graph
COPY api ./api
COPY observability.py ./observability.py

COPY --from=frontend-build /app/frontend/dist ./frontend/dist

ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

# Migrations are idempotent (alembic upgrade head is a no-op once already current),
# so running them on every container start is the safe, simple choice -- no separate
# release step needed.
CMD ["sh", "-c", "alembic -c db/alembic.ini upgrade head && uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
