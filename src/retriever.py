"""Stage 5 — retrieval, reranking, and the abstain gate.

The pipeline decides *before the LLM is ever called* whether the corpus can support an
answer. This is the single most important piece for "does it admit it doesn't know":
if you leave abstention entirely to the prompt, a model under pressure will still
paraphrase a weakly-related chunk. Gating on retrieval scores makes the refusal
deterministic and explainable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import (
    CANDIDATE_K,
    DEFAULT_CORPUS,
    MIN_COSINE,
    MIN_RERANK_SCORE,
    RECENCY_TIE_BAND,
    TOP_K,
    ChunkConfig,
    DEFAULT_CHUNKING,
)
from .embedder import get_embedder, get_reranker
from . import store


@dataclass
class Hit:
    text: str
    meta: dict
    cosine: float
    rerank_score: float | None = None

    @property
    def score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.cosine

    def citation(self) -> str:
        bits = [self.meta.get("title") or self.meta.get("document_id", "?")]
        if self.meta.get("section"):
            bits.append(str(self.meta["section"]))
        if self.meta.get("page"):
            bits.append(f"p.{self.meta['page']}")
        return " > ".join(bits)


@dataclass
class Retrieval:
    query: str
    hits: list[Hit] = field(default_factory=list)
    grounded: bool = False
    reason: str = ""
    diagnostics: dict = field(default_factory=dict)


def build_where(doc_type: str | None = None, effective_on_or_after: str | None = None) -> dict | None:
    """Metadata filtering — narrow the search space *before* the vector comparison.

    Cheap and often more effective than a better embedding model: "only search
    endorsements" or "only documents effective this year" removes whole classes of wrong
    answer before a single vector is compared.
    """
    clauses = []
    if doc_type and doc_type != "all":
        clauses.append({"doc_type": {"$eq": doc_type}})
    if effective_on_or_after:
        clauses.append({"effective_date": {"$gte": effective_on_or_after}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def retrieve(
    question: str,
    cfg: ChunkConfig = DEFAULT_CHUNKING,
    top_k: int = TOP_K,
    candidate_k: int = CANDIDATE_K,
    use_reranker: bool = True,
    where: dict | None = None,
    min_cosine: float | None = None,
    min_rerank_score: float | None = None,
    corpus_id: str = DEFAULT_CORPUS,
    prefer_recent: bool = True,
) -> Retrieval:
    # None means "use the defaults from config"; an explicit number always wins, so the UI
    # sliders and eval/calibrate.py can override per call.
    min_cosine = MIN_COSINE if min_cosine is None else min_cosine
    min_rerank_score = MIN_RERANK_SCORE if min_rerank_score is None else min_rerank_score

    collection = store.get_collection(cfg, corpus_id)
    query_vector = get_embedder().embed_query(question)
    raw = store.query(collection, query_vector, candidate_k, where)

    if not raw:
        return Retrieval(
            question, [], False, "Nothing in the index matched the filters.",
            {"candidates": 0},
        )

    hits = [Hit(text=r["text"], meta=r["meta"], cosine=r["cosine"]) for r in raw]
    best_cosine = max(h.cosine for h in hits)

    if use_reranker:
        scores = get_reranker().score(question, [h.text for h in hits])
        for hit, score in zip(hits, scores):
            hit.rerank_score = round(score, 4)
        if prefer_recent:
            # Near-ties break toward the later effective_date.
            #
            # An amending document and the clause it amends are near-duplicates in meaning,
            # so the cross-encoder scores them almost identically (0.998 vs 1.000 is a
            # typical pair) and their order is effectively arbitrary. When that happens the
            # superseded figure can be handed to the model first, which is how a grounded,
            # correctly-cited answer still ends up wrong.
            #
            # Rounding the score into coarse buckets makes genuine relevance dominate, and
            # only *within* a bucket does recency decide. A clearly better passage still
            # wins regardless of age.
            hits.sort(
                key=lambda h: (
                    round(h.rerank_score / RECENCY_TIE_BAND),
                    str(h.meta.get("effective_date") or ""),
                ),
                reverse=True,
            )
        else:
            hits.sort(key=lambda h: h.rerank_score, reverse=True)

    hits = hits[:top_k]
    best = hits[0]
    diagnostics = {
        "candidates": len(raw),
        "best_cosine": best_cosine,
        "best_rerank": best.rerank_score,
        "reranked": use_reranker,
        "collection": store.collection_name(cfg, corpus_id),
    }

    # Two gates. The cross-encoder is the decisive one when available, because the
    # bi-encoder's cosine floor on this corpus sits around 0.5 even for nonsense.
    if best_cosine < min_cosine:
        return Retrieval(
            question, hits, False,
            f"Best vector similarity {best_cosine:.2f} is below the {min_cosine:.2f} "
            "threshold — nothing in the documents is close enough to this question.",
            diagnostics,
        )

    if use_reranker and best.rerank_score is not None and best.rerank_score < min_rerank_score:
        return Retrieval(
            question, hits, False,
            f"Passages were retrieved, but the cross-encoder scored the best one "
            f"{best.rerank_score:.2f}, below the {min_rerank_score:.2f} threshold — they "
            "are topically near the question but do not answer it.",
            diagnostics,
        )

    return Retrieval(question, hits, True, "", diagnostics)
