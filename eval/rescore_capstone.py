#!/usr/bin/env python
"""Re-apply the CURRENT assertions to a saved integrated-eval run — offline, free, no model.

    python eval/rescore_capstone.py eval/capstone_results_v1_raw.json --out eval/capstone_results_v1.json

Why this exists: reading the first run's failures showed that some assertions were wrong or too
weak (two assertions changed and one gold expectation was an authoring error — see WEEK12.md).
Fixing an assertion must not require re-running 36 cases against a paid, rate-limited model, and
must not touch the original numbers: the raw file is never overwritten. Every host trace already
holds what the assertions need (spans, retrieved ids, the packet), so a run can be re-scored from
``traces/capstone_traces.jsonl`` by trace id.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_capstone_eval as ev                      # noqa: E402
from src import span_log                            # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    old = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    by_trace = {r["trace_id"]: r for r in span_log.read(span_log.TRACES_FILE)}
    rows = []
    for o in old:
        trace = by_trace[o["trace_id"]]
        new = ev.score(trace)
        flipped = [(n, o["assertions"].get(n, {}).get("passed"), c["passed"])
                   for n, c in new["assertions"].items()
                   if o["assertions"].get(n, {}).get("passed") != c["passed"]]
        for n, was, now in flipped:
            print(f"  {o['claim_number']}  {n}: {was} -> {now}")
        rows.append(new)
    Path(args.out).write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    ev.report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
