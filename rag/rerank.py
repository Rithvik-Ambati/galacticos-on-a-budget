"""Cross-encoder reranker. docs/DESIGN.md section 4: BAAI/bge-reranker-base, for
precision on the top-50 candidates the fused BM25+dense pass hands it."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING

from config.settings import get_settings

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder


@lru_cache
def _load_reranker(model_name: str) -> CrossEncoder:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)  # type: ignore[no-any-return]  # sentence_transformers ships no stubs


Reranker = Callable[[str, list[tuple[str, str]]], list[tuple[str, float]]]


def get_reranker(model_name: str | None = None) -> Reranker:
    """Returns rerank(query, [(doc_id, text), ...]) -> [(doc_id, score), ...] sorted
    best first. Loads the cross-encoder lazily and once per process."""
    name = model_name or get_settings().reranker_model
    model = _load_reranker(name)

    def rerank(query: str, candidates: list[tuple[str, str]]) -> list[tuple[str, float]]:
        if not candidates:
            return []
        pairs = [(query, text) for _doc_id, text in candidates]
        scores = model.predict(pairs)
        ranked = sorted(zip((c[0] for c in candidates), scores, strict=True), key=lambda t: -t[1])
        return [(doc_id, float(score)) for doc_id, score in ranked]

    return rerank
