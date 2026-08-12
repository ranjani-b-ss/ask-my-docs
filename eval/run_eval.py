#!/usr/bin/env python
"""Measures retrieval quality across chunking configurations.

    python eval/run_eval.py                 # sweep every config in CHUNK_SWEEP
    python eval/run_eval.py --no-rerank     # bi-encoder only, to isolate the reranker
    python eval/run_eval.py --top-k 3
    python eval/run_eval.py --detail        # per-question pass/fail

Why this measures retrieval and not the written answer: chunk size changes *what the model
is shown*. If the right passage never reaches the prompt, no amount of prompting recovers
it, and if it does reach the prompt the remaining error is the model's. Isolating retrieval
keeps the numbers deterministic — no LLM, so the same command gives the same result.

Metrics
  hit@k     the gold text appears in at least one of the top-k chunks. The headline number:
            "could the model possibly have answered this?"
  MRR       1/rank of the first chunk containing the gold text. Rewards ranking it FIRST,
            not merely somewhere in the window.
  current   superseded questions only: the endorsement chunk outranks the stale base chunk.
            A system can score a perfect hit@k here and still hand the model the wrong
            figure first.
  abstain   unanswerable questions only: the retrieval gate refused. Measured without the
            LLM, so it reflects the gate alone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    CANDIDATE_K,
    CHUNK_SWEEP,
    DEFAULT_CORPUS,
    MIN_COSINE,
    MIN_RERANK_SCORE,
    TOP_K,
)
from src.pipeline import ingest
from src.retriever import retrieve
from src import store

QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.yaml"


def load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))


def _first_rank_containing(hits, needles: list[str], doc_id: str | None) -> int | None:
    """1-based rank of the first hit whose text contains every needle."""
    for rank, hit in enumerate(hits, start=1):
        if doc_id and hit.meta.get("document_id") != doc_id:
            continue
        if all(n.lower() in hit.text.lower() for n in needles):
            return rank
    return None


def evaluate_config(cfg, questions, top_k, use_reranker, corpus, detail=False) -> dict:
    if not store.collection_exists(cfg, corpus):
        ingest(cfg, corpus_id=corpus, verbose=False)

    n_hit = n_gold = 0
    mrr_total = 0.0
    n_current_ok = n_superseded = 0
    n_abstain_ok = n_unanswerable = 0
    rows = []

    for q in questions:
        result = retrieve(
            q["question"], cfg=cfg, corpus_id=corpus, top_k=top_k,
            candidate_k=CANDIDATE_K, use_reranker=use_reranker,
        )
        kind = q["kind"]

        if kind == "unanswerable":
            n_unanswerable += 1
            ok = not result.grounded
            n_abstain_ok += int(ok)
            rows.append((q["id"], kind, "abstained" if ok else "ANSWERED", ""))
            continue

        n_gold += 1
        if kind == "answerable":
            needles, doc_id = q["expect_text"], q.get("expect_doc")
            rank = _first_rank_containing(result.hits, needles, doc_id)
        else:
            n_superseded += 1
            rank = _first_rank_containing(
                result.hits, q["current_text"], q.get("current_doc")
            )
            stale_rank = None
            for alt in q["stale_text"]:
                stale_rank = _first_rank_containing(
                    result.hits, [alt], q.get("stale_doc")
                )
                if stale_rank:
                    break
            if rank and (stale_rank is None or rank < stale_rank):
                n_current_ok += 1

        if rank:
            n_hit += 1
            mrr_total += 1.0 / rank
        rows.append((q["id"], kind, f"rank {rank}" if rank else "MISS", ""))

    if detail:
        print(f"\n  {cfg.describe()}")
        for qid, kind, verdict, _ in rows:
            flag = "  " if verdict.startswith(("rank 1", "abstained")) else "! "
            print(f"   {flag}{qid:<30} {kind:<13} {verdict}")

    count = store.get_collection(cfg, corpus).count()
    return {
        "config": cfg.describe(),
        "chunks": count,
        "hit_at_k": n_hit / n_gold if n_gold else 0.0,
        "mrr": mrr_total / n_gold if n_gold else 0.0,
        "current_wins": n_current_ok / n_superseded if n_superseded else 0.0,
        "abstain": n_abstain_ok / n_unanswerable if n_unanswerable else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Chunking sweep for the RAG pipeline")
    parser.add_argument("--top-k", type=int, default=TOP_K)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--detail", action="store_true")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    args = parser.parse_args()

    questions = load_questions()
    n_gold = sum(1 for q in questions if q["kind"] != "unanswerable")
    n_unans = len(questions) - n_gold

    print(f"{len(questions)} questions: {n_gold} with a gold answer, {n_unans} unanswerable")
    print(f"top_k={args.top_k}  candidate_k={CANDIDATE_K}  "
          f"reranker={'off' if args.no_rerank else 'on'}")
    print(f"gates: cosine >= {MIN_COSINE}, rerank >= {MIN_RERANK_SCORE}")

    results = [
        evaluate_config(cfg, questions, args.top_k, not args.no_rerank,
                        args.corpus, args.detail)
        for cfg in CHUNK_SWEEP
    ]

    print(f"\n| {'chunking':<28} | chunks | hit@k | MRR  | current | abstain |")
    print(f"| {'-'*28} | -----: | ----: | ---: | ------: | ------: |")
    for r in results:
        print(f"| {r['config']:<28} | {r['chunks']:>6} | {r['hit_at_k']:>5.0%} | "
              f"{r['mrr']:>4.2f} | {r['current_wins']:>7.0%} | {r['abstain']:>7.0%} |")

    best = max(results, key=lambda r: (r["mrr"], r["hit_at_k"]))
    print(f"\nbest by MRR: {best['config']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
