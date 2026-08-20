"""Keyword search (BM25), for hybrid retrieval.

Dense embeddings match *meaning*. That is what makes them good — and it is exactly why they
miss things a human would call obvious:

    a policy number, a UIN, an error code, a plan name, a clause reference

Those carry almost no semantic content. To an embedding model, ``512N338V01`` and
``512N339V02`` are near-identical, and a rare token in a query is easily outvoted by the
surrounding words. BM25 has the opposite bias: it rewards rare exact tokens heavily and
knows nothing about meaning.

Combining them (see ``retriever.reciprocal_rank_fusion``) covers both cases without tuning
anything per corpus — which is the point. No stop-word list for insurance, no
keyword-boosting rules for policy documents. Just term statistics computed from whatever
text the corpus happens to contain.

Implemented in ~80 lines of standard library rather than pulling in a dependency: the maths
is short, and having it visible makes it reviewable.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Split on anything that is not alphanumeric, but KEEP digits attached to letters so
# identifiers survive as single tokens: "512n338v01" stays whole, "end-2026-01" becomes
# "end", "2026", "01". Splitting identifiers entirely would throw away the exact-match
# advantage that justifies BM25 being here at all.
_TOKEN = re.compile(r"[a-z0-9]+")

# BM25 constants, standard values. k1 controls how fast term-frequency saturates; b controls
# how much document length is penalised.
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25:
    """A tiny BM25 index over a fixed list of documents."""

    def __init__(self, documents: list[str]):
        self.docs_tokens = [tokenize(d) for d in documents]
        self.doc_lengths = [len(t) for t in self.docs_tokens]
        self.n_docs = len(documents)
        self.avg_len = (sum(self.doc_lengths) / self.n_docs) if self.n_docs else 0.0

        # term -> number of documents containing it
        doc_freq: Counter[str] = Counter()
        for tokens in self.docs_tokens:
            doc_freq.update(set(tokens))

        # Inverse document frequency. A term in every chunk carries no signal; a term in one
        # chunk carries a lot. This is what makes a rare policy number so decisive.
        self.idf: dict[str, float] = {
            term: math.log(1 + (self.n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }
        self.term_freqs = [Counter(tokens) for tokens in self.docs_tokens]

    def score(self, query: str) -> list[float]:
        """BM25 score of the query against every document, in document order."""
        terms = tokenize(query)
        scores = [0.0] * self.n_docs
        if not terms or not self.n_docs:
            return scores

        for term in terms:
            idf = self.idf.get(term)
            if idf is None:
                continue   # term appears nowhere in the corpus
            for i, freqs in enumerate(self.term_freqs):
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                norm = 1 - B + B * (self.doc_lengths[i] / self.avg_len) if self.avg_len else 1
                scores[i] += idf * (tf * (K1 + 1)) / (tf + K1 * norm)
        return scores

    def top_n(self, query: str, n: int) -> list[tuple[int, float]]:
        """Return (document index, score) for the n best matches, score > 0 only."""
        scored = [(i, s) for i, s in enumerate(self.score(query)) if s > 0]
        scored.sort(key=lambda p: -p[1])
        return scored[:n]


# One index per collection, built on first use. Chunk text never changes for a given
# collection (ingest creates a fresh one), so the cache cannot go stale.
_cache: dict[str, tuple[BM25, list[str], list[dict]]] = {}


def get_index(collection) -> tuple[BM25, list[str], list[dict]]:
    """Build (or fetch) the BM25 index for a Chroma collection.

    Reads the chunk text straight out of Chroma rather than persisting a second copy — one
    source of truth, and nothing to invalidate when a corpus is re-ingested.
    """
    name = collection.name
    if name not in _cache:
        got = collection.get(include=["documents", "metadatas"])
        docs = got["documents"] or []
        metas = got["metadatas"] or []
        _cache[name] = (BM25(docs), docs, metas)
    return _cache[name]


def invalidate(collection_name: str | None = None) -> None:
    if collection_name is None:
        _cache.clear()
    else:
        _cache.pop(collection_name, None)
