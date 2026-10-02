# Production image for the API. Built, never run in this build (user instruction:
# "don't deploy yet") -- authored to the same stack docs/DESIGN.md section 4 names.

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

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
