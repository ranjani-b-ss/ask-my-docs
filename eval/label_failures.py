#!/usr/bin/env python
"""Week 4 · separate retrieval failures from generation failures.

    python eval/label_failures.py --corpus insurance --k 3
    python eval/label_failures.py --corpus uploaded --questions eval/questions_lic.yaml
    python eval/label_failures.py --no-llm        # retrieval-side labels only, no API calls

"Wrong sometimes" is useless to act on, because the two kinds of wrong need opposite fixes:

    RETRIEVAL_FAIL   the gold passage never reached the top-k. The model was handed the
                     wrong material and had no chance. A smarter or costlier model changes
                     NOTHING here — the fix is chunking, embeddings, hybrid search, or
                     reranking.

    GEN_FAIL_GATED   the gold passage WAS in the top-k, but an abstain gate refused before
                     the model saw it. Retrieval worked; the threshold was wrong. The fix is
                     calibration, not retrieval.

    GEN_FAIL_WRONG   the gold passage was in the top-k, the model answered, and the answer
                     missed the gold fact. The fix is the prompt or the model.

    FALSE_ANSWER     an unanswerable question got answered. The abstain gates let it through.

Separating GATED from WRONG matters: both look like "right document, wrong answer" from the
outside, but one is a number in config.py and the other is a prompt.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import CANDIDATE_K, DEFAULT_CHUNKING, DEFAULT_CORPUS, ChunkConfig
from src.generator import answer_from_retrieval
from src.retriever import retrieve
from src import llm, store

PASS = "PASS"
RETRIEVAL_FAIL = "RETRIEVAL_FAIL"
GEN_FAIL_GATED = "GEN_FAIL_GATED"
GEN_FAIL_WRONG = "GEN_FAIL_WRONG"
FALSE_ANSWER = "FALSE_ANSWER"
UNKNOWN = "UNCHECKED_NO_LLM"


def gold_texts(q: dict) -> list[str]:
    """The strings that must appear in the right chunk for this question to count as found."""
    if q["kind"] == "superseded":
        return q.get("current_text", [])
    return q.get("expect_text", [])


def gold_doc(q: dict) -> str | None:
    return q.get("current_doc") if q["kind"] == "superseded" else q.get("expect_doc")


def found_in(hits, needles: list[str], doc_id: str | None) -> int | None:
    """1-based rank of the first hit containing every needle, or None."""
    if not needles:
        return None
    for rank, hit in enumerate(hits, start=1):
        if doc_id and hit.meta.get("document_id") != doc_id:
            continue
        if all(n.lower() in hit.text.lower() for n in needles):
            return rank
    return None


def relevant_chunk_count(collection, needles: list[str], doc_id: str | None) -> int:
    """How many chunks in the whole collection actually contain this answer.

    Needed for a real Recall@K. Hit-rate@k asks "did *any* correct chunk make the cut" —
    a yes/no. Recall@k asks "what fraction of the correct chunks made the cut", which needs
    the size of the relevant set, not just one gold chunk.

    The counts are usually >1 here, because chunk overlap deliberately repeats the tail of
    one chunk at the head of the next, so a fact near a boundary genuinely lives in two
    chunks. That is what makes recall meaningfully different from hit-rate on this corpus
    rather than a duplicate column.
    """
    if not needles:
        return 0
    got = collection.get(include=["documents", "metadatas"])
    docs = got["documents"] or []
    metas = got["metadatas"] or []
    count = 0
    for text, meta in zip(docs, metas):
        if doc_id and meta.get("document_id") != doc_id:
            continue
        if all(n.lower() in text.lower() for n in needles):
            count += 1
    return count


def relevant_retrieved(hits, needles: list[str], doc_id: str | None) -> int:
    """How many of the retrieved hits are relevant (the numerator of Recall@K)."""
    if not needles:
        return 0
    n = 0
    for hit in hits:
        if doc_id and hit.meta.get("document_id") != doc_id:
            continue
        if all(x.lower() in hit.text.lower() for x in needles):
            n += 1
    return n


def label_one(q: dict, cfg: ChunkConfig, corpus: str, k: int, use_llm: bool,
              collection=None, use_hybrid: bool = True, use_reranker: bool = True) -> dict:
    # Gates OFF for the retrieval probe: we need to know whether the passage was *found*,
    # independently of whether a threshold later refused it. Conflating the two is exactly
    # the mistake this script exists to prevent.
    probe = retrieve(q["question"], cfg=cfg, corpus_id=corpus, top_k=k,
                     candidate_k=CANDIDATE_K, min_cosine=0.0, min_rerank_score=0.0,
                     use_hybrid=use_hybrid, use_reranker=use_reranker)
    rank = found_in(probe.hits, gold_texts(q), gold_doc(q))

    # Now the real pipeline, gates ON, exactly as a user would experience it.
    live = retrieve(q["question"], cfg=cfg, corpus_id=corpus, top_k=k,
                    candidate_k=CANDIDATE_K, use_hybrid=use_hybrid,
                    use_reranker=use_reranker)
    answer = answer_from_retrieval(live, force_extractive=not use_llm)

    # Recall@K needs the size of the relevant set, not just whether one gold chunk landed.
    needles, doc_id = gold_texts(q), gold_doc(q)
    n_relevant = relevant_chunk_count(collection, needles, doc_id) if collection else 0
    n_got = relevant_retrieved(probe.hits, needles, doc_id)

    row = {
        "id": q["id"], "kind": q["kind"], "rank": rank,
        "grounded": answer.grounded, "mode": answer.mode,
        "n_relevant": n_relevant, "n_retrieved_relevant": n_got,
        "recall": (n_got / n_relevant) if n_relevant else None,
        "rr": (1.0 / rank) if rank else 0.0,          # reciprocal rank, for MRR
        "best_cosine": live.diagnostics.get("best_cosine"),
        "best_rerank": live.diagnostics.get("best_rerank"),
        "hybrid": live.diagnostics.get("hybrid"),
    }

    if q["kind"] == "unanswerable":
        if not answer.grounded:
            row["label"] = PASS                # correctly refused
        elif answer.mode == "extractive":
            # No model ran (none configured, or the call failed and we degraded to quoting
            # a passage). Nothing judged this question, so calling it a false answer would
            # blame the app for a decision it never made. A mislabel is worse than a gap.
            row["label"] = UNKNOWN
        else:
            row["label"] = FALSE_ANSWER        # a model saw the passages and answered anyway
        return row

    if rank is None:
        # Never reached the top-k. Nothing downstream could have saved it.
        row["label"] = RETRIEVAL_FAIL
        return row

    if not answer.grounded:
        # Found it, then refused it. That is a threshold problem, not a retrieval one.
        row["label"] = GEN_FAIL_GATED
        return row

    if answer.mode == "extractive":
        # No model ran, so "did the wording capture the fact?" is unanswerable here.
        row["label"] = PASS if rank == 1 else UNKNOWN
        return row

    hit = all(n.lower() in answer.text.lower() for n in gold_texts(q))
    row["label"] = PASS if hit else GEN_FAIL_WRONG
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="Label failures: retrieval vs generation")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--questions", default="eval/questions.yaml")
    ap.add_argument("--k", type=int, default=3, help="top-k for hit-rate@k (brief asks for 3)")
    ap.add_argument("--no-llm", action="store_true", help="skip generation, label retrieval only")
    ap.add_argument("--strategy", default=DEFAULT_CHUNKING.strategy)
    ap.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNKING.chunk_size)
    ap.add_argument("--overlap", type=int, default=DEFAULT_CHUNKING.overlap)
    ap.add_argument("--no-hybrid", action="store_true",
                    help="dense-only retrieval — the BEFORE side of the benchmark")
    ap.add_argument("--no-rerank", action="store_true",
                    help="skip the cross-encoder (faster, and isolates the hybrid change)")
    args = ap.parse_args()

    cfg = ChunkConfig(args.strategy, args.chunk_size, args.overlap)
    if not store.collection_exists(cfg, args.corpus):
        print(f"No index for '{args.corpus}' at {cfg.describe()}. Run: "
              f"python cli.py --corpus {args.corpus} ingest", file=sys.stderr)
        return 1

    use_llm = not args.no_llm and llm.is_ready()
    if not args.no_llm and not use_llm:
        print(f"! {llm.status().detail}\n! Falling back to retrieval-only labelling — "
              f"GEN_FAIL_WRONG cannot be detected without a model.\n")

    questions = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))
    collection = store.get_collection(cfg, args.corpus)
    rows = [label_one(q, cfg, args.corpus, args.k, use_llm, collection,
                      use_hybrid=not args.no_hybrid, use_reranker=not args.no_rerank)
            for q in questions]

    print(f"corpus {args.corpus} · {cfg.describe()} · k={args.k} · "
          f"hybrid={'OFF' if args.no_hybrid else 'ON'} · "
          f"rerank={'off' if args.no_rerank else 'on'} · "
          f"llm={'on' if use_llm else 'off'}\n")
    print(f"  {'question':<28} {'kind':<13} {'rank':>4}  {'cos':>5} {'rr':>5}  label")
    print(f"  {'-'*28} {'-'*13} {'-'*4}  {'-'*5} {'-'*5}  {'-'*16}")
    for r in sorted(rows, key=lambda r: (r["label"] == PASS, r["id"])):
        rank = str(r["rank"]) if r["rank"] else "—"
        flag = "  " if r["label"] == PASS else "! "
        print(f" {flag}{r['id']:<28} {r['kind']:<13} {rank:>4}  "
              f"{r['best_cosine'] or 0:>5.3f} {r['best_rerank'] or 0:>5.3f}  {r['label']}")

    counts = Counter(r["label"] for r in rows)
    answerable = [r for r in rows if r["kind"] != "unanswerable"]
    hits_at_k = sum(1 for r in answerable if r["rank"] is not None)

    # The three metrics the brief asks for, over the answerable questions only.
    n = len(answerable)
    hit_rate = hits_at_k / n
    recalls = [r["recall"] for r in answerable if r["recall"] is not None]
    recall_at_k = sum(recalls) / len(recalls) if recalls else 0.0
    mrr = sum(r["rr"] for r in answerable) / n

    print(f"\n  METRICS over {n} answerable questions (k={args.k})")
    print(f"    Hit-Rate@{args.k} : {hits_at_k}/{n} = {hit_rate:.1%}   "
          f"<-- at least one correct chunk in top-{args.k}")
    print(f"    Recall@{args.k}   : {recall_at_k:.1%}   "
          f"<-- mean fraction of ALL correct chunks retrieved")
    print(f"    MRR         : {mrr:.3f}   "
          f"<-- 1/rank of the first correct chunk, averaged")
    print(f"\n  labels: " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    n_retr = counts.get(RETRIEVAL_FAIL, 0)
    n_gen = counts.get(GEN_FAIL_GATED, 0) + counts.get(GEN_FAIL_WRONG, 0)
    print(f"\n  retrieval-side failures : {n_retr}  (fix = chunking / hybrid / reranking)")
    print(f"  generation-side failures: {n_gen}  (fix = thresholds / prompt / model)")
    print(f"  false answers           : {counts.get(FALSE_ANSWER, 0)}  (fix = abstain gates)")
    if n_retr and n_gen:
        print(f"\n  Both kinds present — a single fix cannot clear both. Pick the larger "
              f"bucket first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
