#!/usr/bin/env python
"""Drive real traffic through the app so there is a trace log to read.

    python scripts/generate_traffic.py                      # the random population
    python scripts/generate_traffic.py --bank eval/demo_set.yaml --surface demo
    python scripts/generate_traffic.py --sleep 6            # slower, for a tight rate limit

This is not an eval harness. It asserts nothing, scores nothing, and has no gold answers —
it exists only to produce traces. Every question goes through ``pipeline.ask`` exactly as a
user's would, so the traces are the real thing rather than a reconstruction.

Interruptions are safe: traces are appended one line at a time, so a run stopped by a rate
limit or Ctrl-C leaves every completed trace intact.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DEFAULT_CHUNKING, TRACE_FILE
from src.pipeline import ask
from src import store


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate traces by asking real questions")
    ap.add_argument("--bank", default="eval/traffic_bank.yaml")
    ap.add_argument("--surface", default=None,
                    help="trace surface label; defaults to the bank's 'set' field")
    ap.add_argument("--sleep", type=float, default=4.0,
                    help="seconds between questions, to stay inside the provider rate limit")
    ap.add_argument("--limit", type=int, default=0, help="stop after N questions (0 = all)")
    args = ap.parse_args()

    bank = yaml.safe_load(Path(args.bank).read_text(encoding="utf-8"))
    questions = bank["questions"]
    if args.limit:
        questions = questions[: args.limit]
    surface = args.surface or f"traffic-{bank.get('set', 'random')}"

    # Fail before the first question rather than half way through: a missing index would
    # otherwise write dozens of identical error traces and pollute the population.
    for corpus in sorted({q["corpus"] for q in questions}):
        if not store.collection_exists(DEFAULT_CHUNKING, corpus):
            print(f"No index for corpus '{corpus}'. Run: "
                  f"python cli.py --corpus {corpus} ingest", file=sys.stderr)
            return 1

    print(f"{len(questions)} questions -> {TRACE_FILE}  (surface={surface})\n")
    counts: dict[str, int] = {}
    for i, item in enumerate(questions, start=1):
        question, corpus = item["q"], item["corpus"]
        try:
            result = ask(question, corpus_id=corpus, surface=surface)
            key = f"{result.mode}/{'grounded' if result.grounded else 'abstained'}"
        except KeyboardInterrupt:
            print("\ninterrupted — traces written so far are intact")
            return 130
        except Exception as exc:
            key = f"error/{type(exc).__name__}"
            print(f"  ! {exc}")
        counts[key] = counts.get(key, 0) + 1
        print(f"  {i:>3}/{len(questions)}  [{corpus:<9}] {key:<24} {question[:56]}")
        if args.sleep and i < len(questions):
            time.sleep(args.sleep)

    print("\noutcome mix:")
    for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4}  {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
