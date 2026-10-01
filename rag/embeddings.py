"""Embedding model loader. docs/DESIGN.md section 4: BAAI/bge-small-en-v1.5 baseline,
chosen over bge-base/e5-base by the recall-vs-latency benchmark in evals/.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING

from config.settings import get_settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

Embedder = Callable[[str], list[float]]


@lru_cache
def _load_model(model_name: str) -> SentenceTransformer:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def get_embedder(model_name: str | None = None) -> Embedder:
    """Returns a callable text -> embedding vector. Loads the model lazily and once —
    tests and any environment without the model cached can pass `embedder=None`
    wherever this is consumed instead of calling this at all."""
    name = model_name or get_settings().embedding_model
    model = _load_model(name)

    def embed(text: str) -> list[float]:
        return [float(v) for v in model.encode(text, normalize_embeddings=True)]

    return embed
