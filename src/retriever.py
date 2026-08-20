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
from . import keyword, store


@dataclass
class Hit:
    text: str
    meta: dict
    cosine: float
    rerank_score: float | None = None
    bm25: float | None = None      # keyword score, None when hybrid is off
    rrf: float | None = None       # fused rank score

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


RRF_K = 60   # standard damping constant; large enough that rank 1 vs 2 is not a landslide


def reciprocal_rank_fusion(*ranked_lists: list[str], k: int = RRF_K) -> dict[str, float]:
    """Fuse several ranked ID lists into one score per ID.

    Each list contributes ``1 / (k + rank)``. The appeal is that it needs no score
    normalisation: cosine similarity (0-1) and BM25 (unbounded) are not comparable as
    numbers, but their *ranks* always are. That is why RRF is the default fusion for hybrid
    search rather than a weighted score sum, which would need per-corpus tuning of the
    weights — exactly the corpus-specific fitting we want to avoid.

    An item ranked highly by both retrievers beats one ranked highly by only one, which is
    the whole point: agreement between two different notions of relevance is evidence.
    """
    fused: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (k + rank)
    return fused


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
    use_hybrid: bool = True,
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
    fused_in = 0

    if use_hybrid and where is None:
        # Keyword search over the same collection, fused by rank. Skipped when a metadata
        # filter is active: BM25 here scans the whole collection, so fusing its results
        # would smuggle back chunks the filter deliberately excluded.
        bm25, docs, metas = keyword.get_index(collection)
        kw = bm25.top_n(question, candidate_k)
        if kw:
            by_text = {h.text: h for h in hits}
            for idx, score in kw:
                text = docs[idx]
                if text in by_text:
                    by_text[text].bm25 = round(score, 4)
                else:
                    # Found by keywords but missed by the vector search entirely — this is
                    # the class of result hybrid exists to recover.
                    extra = Hit(text=text, meta=metas[idx], cosine=0.0)
                    extra.bm25 = round(score, 4)
                    hits.append(extra)
                    by_text[text] = extra
                    fused_in += 1

            dense_order = [r["text"] for r in raw]
            kw_order = [docs[i] for i, _ in kw]
            fused = reciprocal_rank_fusion(dense_order, kw_order)
            for h in hits:
                h.rrf = round(fused.get(h.text, 0.0), 6)
            hits.sort(key=lambda h: h.rrf or 0.0, reverse=True)
            hits = hits[:candidate_k]

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
        "hybrid": use_hybrid and where is None,
        "keyword_only_candidates": fused_in,
        "best_bm25": max((h.bm25 or 0.0 for h in hits), default=0.0),
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
