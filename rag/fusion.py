"""Reciprocal Rank Fusion. docs/DESIGN.md section 8: RRF, k=60."""

from __future__ import annotations

DEFAULT_K = 60


def rrf_fuse(ranked_lists: list[list[str]], k: int = DEFAULT_K) -> list[tuple[str, float]]:
    """ranked_lists: each a list of doc_ids, best first. Returns (doc_id, rrf_score)
    sorted best first."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda t: -t[1])
