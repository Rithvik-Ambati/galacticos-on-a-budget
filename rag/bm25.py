"""In-process BM25 lexical search. docs/DESIGN.md section 4: `rank_bm25` because
Postgres `ts_rank` is not true BM25, and the corpus (~1k docs) comfortably fits in
memory."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Bm25Hit:
    doc_id: str
    score: float


class Bm25Index:
    def __init__(self, doc_ids: list[str], texts: list[str]) -> None:
        self.doc_ids = doc_ids
        # BM25Okapi([]) raises ZeroDivisionError computing the average document length
        # -- a real crash this hit on its very first empty-corpus test, not a mock gap.
        self._bm25 = BM25Okapi([tokenize(t) for t in texts]) if texts else None

    @classmethod
    def from_documents(cls, documents: list[tuple[str, str]]) -> Bm25Index:
        """documents: list of (doc_id, text)."""
        if not documents:
            return cls([], [])
        doc_ids, texts = zip(*documents, strict=True)
        return cls(list(doc_ids), list(texts))

    def search(self, query: str, top_k: int = 50) -> list[Bm25Hit]:
        if not self.doc_ids or self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(self.doc_ids, scores, strict=True), key=lambda t: -t[1])
        return [Bm25Hit(doc_id, float(score)) for doc_id, score in ranked[:top_k] if score > 0]
