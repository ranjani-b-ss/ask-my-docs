#!/usr/bin/env python
"""Recalibrate the abstain thresholds for a corpus.

    python eval/calibrate.py --corpus uploaded --questions eval/questions_lic.yaml

Why this exists: the thresholds in config.py are not universal constants. A cross-encoder's
score distribution shifts with the *prose* it is scoring. Clean synthetic Markdown scores
genuine answers 0.3–1.0 and non-answers at ~0.000, so a 0.35 cut separates them cleanly.
Real PDF text — hyphen-broken words, ragged spacing, "wi thin" instead of "within" — scores
lower across the board, and the same 0.35 starts refusing questions the corpus can answer.

So the threshold is a measured property of a corpus, not a setting to guess. This script
measures the two score distributions and reports the cut that separates them best.

Read the output as a trade, not an answer: raising the threshold refuses more real
questions, lowering it lets more junk through. The script shows the cost of each.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import CANDIDATE_K, DEFAULT_CHUNKING, DEFAULT_CORPUS, TOP_K
from src.retriever import retrieve
from src import store


def measure(questions: list[dict], corpus: str, cfg) -> tuple[list, list]:
    """Return (answerable_scores, unanswerable_scores) as (question, cosine, rerank)."""
    answerable, unanswerable = [], []
    for q in questions:
        # Thresholds are set to 0 so nothing is gated — we want the raw scores.
        r = retrieve(
            q["question"], cfg=cfg, corpus_id=corpus, top_k=TOP_K,
            candidate_k=CANDIDATE_K, use_reranker=True,
            min_cosine=0.0, min_rerank_score=0.0,
        )
        best_cos = max((h.cosine for h in r.hits), default=0.0)
        best_rr = max((h.rerank_score or 0.0 for h in r.hits), default=0.0)
        row = (q["id"], best_cos, best_rr)
        (unanswerable if q["kind"] == "unanswerable" else answerable).append(row)
    return answerable, unanswerable


def best_split(pos: list[float], neg: list[float]) -> tuple[float, int, int]:
    """Find the threshold maximising (kept answerable + refused unanswerable)."""
    best = (0.0, -1, 0, 0)
    for step in range(0, 101):
        t = step / 100
        kept = sum(1 for v in pos if v >= t)
        refused = sum(1 for v in neg if v < t)
        score = kept + refused
        if score > best[1]:
            best = (t, score, kept, refused)
    return best[0], best[2], best[3]


def report(label: str, answerable, unanswerable, idx: int) -> None:
    pos = sorted(r[idx] for r in answerable)
    neg = sorted(r[idx] for r in unanswerable)
    print(f"\n{label}")
    print(f"  answerable   n={len(pos):2}  min={pos[0]:.3f}  median={pos[len(pos)//2]:.3f}  max={pos[-1]:.3f}")
    print(f"  unanswerable n={len(neg):2}  min={neg[0]:.3f}  median={neg[len(neg)//2]:.3f}  max={neg[-1]:.3f}")
    overlap = pos[0] <= neg[-1]
    print(f"  separable cleanly: {'NO — the distributions overlap' if overlap else 'yes'}")
    t, kept, refused = best_split(pos, neg)
    print(f"  best threshold {t:.2f} → keeps {kept}/{len(pos)} answerable, "
          f"refuses {refused}/{len(neg)} unanswerable")
    if overlap:
        print(f"  overlap band: {neg[-1]:.3f} (worst non-answer) down to {pos[0]:.3f} "
              f"(weakest real answer) — questions in this band cannot be separated by "
              f"this signal alone")


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrate abstain thresholds for a corpus")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--questions", default="eval/questions.yaml")
    ap.add_argument("--detail", action="store_true", help="print every question's scores")
    args = ap.parse_args()

    cfg = DEFAULT_CHUNKING
    if not store.collection_exists(cfg, args.corpus):
        print(f"No index for corpus '{args.corpus}'. Run: "
              f"python cli.py --corpus {args.corpus} ingest", file=sys.stderr)
        return 1

    questions = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))
    answerable, unanswerable = measure(questions, args.corpus, cfg)

    print(f"corpus '{args.corpus}' · {cfg.describe()} · "
          f"{len(answerable)} answerable, {len(unanswerable)} unanswerable")

    if args.detail:
        print(f"\n  {'question':<34} {'cosine':>7} {'rerank':>7}  kind")
        for rows, kind in ((answerable, "answerable"), (unanswerable, "unanswerable")):
            for qid, cos, rr in sorted(rows, key=lambda r: -r[2]):
                print(f"  {qid:<34} {cos:>7.3f} {rr:>7.3f}  {kind}")

    report("COSINE (bi-encoder)", answerable, unanswerable, 1)
    report("RERANK (cross-encoder)", answerable, unanswerable, 2)

    print("\nApply by setting MIN_COSINE / MIN_RERANK_SCORE in src/config.py, or per-call "
          "in the UI sidebar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
