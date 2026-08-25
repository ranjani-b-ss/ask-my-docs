#!/usr/bin/env python
"""Draw a seeded random sample of traces to read by hand.

    python eval/sample_traces.py --seed 20260826 --n 20
    python eval/sample_traces.py --seed 20260826 --n 10 --population traffic-demo
    python eval/sample_traces.py --seed 20260826 --n 20 --print-full   # full trace bodies

Why a seed instead of just picking twenty: the sample has to be *checkable*. Anyone with
the trace file and the seed gets the identical twenty trace_ids, so the frequencies in
taxonomy.md can be audited rather than believed. Without that, "we read a random sample" is
an unfalsifiable claim, and a reader has no way to tell it from twenty cherry-picked ones.

Two rules that keep the sample honest:

  * The demo traces are excluded by default. They are the questions the app is shown with,
    so they are the least representative population available — sampling them would produce
    a frequency table describing the demo rather than the product.
  * Selection is over the sorted trace_id list, not over file order. File order depends on
    when the traffic script happened to run; sorting makes the draw depend only on the seed
    and the population.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import TRACE_FILE
from src import trace


def population(rows: list[dict], surface_prefix: str) -> list[dict]:
    return [r for r in rows if str(r.get("surface", "")).startswith(surface_prefix)]


def draw(rows: list[dict], seed: int, n: int) -> list[dict]:
    by_id = {r["trace_id"]: r for r in rows}
    ids = sorted(by_id)                     # order must not depend on file order
    if n > len(ids):
        raise SystemExit(f"asked for {n} traces but the population has only {len(ids)}")
    chosen = random.Random(seed).sample(ids, n)
    return [by_id[i] for i in chosen]


def main() -> int:
    ap = argparse.ArgumentParser(description="Seeded random sample of traces")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--population", default="traffic-random",
                    help="surface prefix to sample from (default excludes the demo set)")
    ap.add_argument("--print-full", action="store_true",
                    help="dump each sampled trace in full, for the hand-reading pass")
    ap.add_argument("--ids-only", action="store_true")
    args = ap.parse_args()

    rows = trace.read_all()
    if not rows:
        raise SystemExit(f"No traces in {TRACE_FILE}. Run scripts/generate_traffic.py first.")

    pool = population(rows, args.population)
    sample = draw(pool, args.seed, args.n)

    if args.ids_only:
        for r in sample:
            print(r["trace_id"])
        return 0

    print(f"trace file      : {TRACE_FILE}")
    print(f"total traces    : {len(rows)}")
    print(f"population      : surface startswith '{args.population}' -> {len(pool)} traces")
    print(f"seed            : {args.seed}")
    print(f"sample size     : {args.n}  ({args.n / len(pool):.0%} of the population)")
    print(f"selection       : random.Random(seed).sample(sorted(trace_ids), n)\n")

    for i, r in enumerate(sample, start=1):
        print(f"{i:>3}. {r['trace_id']}  [{r['corpus']:<9}] {r['mode']:<11} "
              f"gate={r['gate'] or '-':<19} {r['question'][:60]}")

    mix = Counter(f"{r['mode']}/{'grounded' if r['grounded'] else 'abstained'}" for r in sample)
    print("\nsample outcome mix (NOT a taxonomy — just what the labels say):")
    for key, n in sorted(mix.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {key}")

    if args.print_full:
        print("\n" + "=" * 100)
        for i, r in enumerate(sample, start=1):
            print(f"\n{'=' * 100}\n### {i}. {r['trace_id']}\n{'=' * 100}")
            print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
