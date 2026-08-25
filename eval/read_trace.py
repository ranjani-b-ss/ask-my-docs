#!/usr/bin/env python
"""Print traces in a form a human can actually read, for the open-coding pass.

    python eval/read_trace.py --seed 20260826 --n 20 --from 1 --to 5
    python eval/read_trace.py --trace-id tr_9e0edc592659 --chars 1200

The raw JSONL is unreadable at this length, and reading it badly is how you end up
open-coding the label instead of the event. So this pulls the actual chunk TEXT out of the
store for each retrieved chunk_id and shows it next to the answer. Without the passage text
you cannot tell a wrong answer from a right answer over the wrong passage — they look
identical in the JSON, and they need opposite fixes.

Read-only. It touches nothing and writes nothing.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ChunkConfig
from src import store, trace


def wrap(text: str, width: int = 96, indent: str = "      ") -> str:
    out = []
    for para in (text or "").strip().split("\n"):
        out.extend(textwrap.wrap(para, width=width, initial_indent=indent,
                                 subsequent_indent=indent) or [indent])
    return "\n".join(out)


def show(row: dict, n: int, chars: int) -> None:
    print("\n" + "=" * 104)
    print(f"### {n}. {row['trace_id']}   [{row['corpus']}]   {row['ts']}")
    print("=" * 104)
    print(f"QUESTION : {row['question']}")
    print(f"OUTCOME  : mode={row['mode']}  grounded={row['grounded']}  "
          f"gate={row['gate'] or '-'}")
    print(f"SCORES   : best_cos={max((h['cosine'] or 0) for h in row['retrieved']):.3f}  "
          f"best_rerank={max((h['rerank'] or 0) for h in row['retrieved']):.3f}  "
          f"floors: cos>={row['min_cosine']} rerank>={row['min_rerank_score']}")
    if row["gate_detail"]:
        print(f"GATE SAYS: {row['gate_detail'][:220]}")
    print(f"MODEL    : {row['provider'] or '(none called)'} {row['model']} "
          f"{row['params']}   latency={row['latency_ms']}ms")

    cfg = ChunkConfig(**row["chunking"])
    collection = store.get_collection(cfg, row["corpus"])
    fetched = store.get_by_ids(collection, [h["chunk_id"] for h in row["retrieved"]])

    print(f"\nRETRIEVED ({len(row['retrieved'])} passages, in the order the model saw them)")
    for h in row["retrieved"]:
        got = fetched.get(h["chunk_id"])
        print(f"\n  [{h['rank']}] {h['chunk_id']}")
        print(f"      doc={h['document_id']}  eff={h['effective_date'] or '-'}  "
              f"page={h['page'] or '-'}")
        print(f"      cos={h['cosine']}  rerank={h['rerank']}  bm25={h['bm25']}  "
              f"rrf={h['rrf']}")
        print(f"      section: {h['section'] or '(none)'}")
        if got:
            print(wrap(got["text"][:chars]))
        else:
            print("      (chunk no longer in the index)")

    print("\nRAW MODEL OUTPUT")
    print(wrap(row["raw_output"], indent="      ") if row["raw_output"]
          else "      (no model call)")
    print("\nWHAT THE USER SAW")
    print(wrap(row["answer"], indent="      "))
    if row["citations"]:
        print("\nCITATIONS SHOWN")
        for c in row["citations"]:
            print(f"      [{c['n']}] {c['label']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Read traces by hand")
    ap.add_argument("--trace-id")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--population", default="traffic-random")
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--to", dest="end", type=int, default=0)
    ap.add_argument("--chars", type=int, default=700, help="chunk text shown per passage")
    args = ap.parse_args()

    rows = trace.read_all()
    if args.trace_id:
        row = next((r for r in rows if r["trace_id"] == args.trace_id), None)
        if row is None:
            raise SystemExit(f"no trace {args.trace_id}")
        show(row, 1, args.chars)
        return 0

    if args.seed is None:
        raise SystemExit("pass --seed or --trace-id")

    from sample_traces import draw, population

    sample = draw(population(rows, args.population), args.seed, args.n)
    end = args.end or len(sample)
    for i in range(args.start, min(end, len(sample)) + 1):
        show(sample[i - 1], i, args.chars)
    return 0


if __name__ == "__main__":
    sys.exit(main())
