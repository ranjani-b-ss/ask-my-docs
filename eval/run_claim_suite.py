#!/usr/bin/env python
"""Week 11 — THE suite. Every claim in race_cases.yaml, graded against gold, through the
single agent (react_agent.py — the system Week 10's race recommended shipping;
orchestrator.py is not re-covered here, see WEEK11.md for why that's a deliberate scope
line, not an oversight).

    python eval/run_claim_suite.py                          # one pass, real traces written
    python eval/run_claim_suite.py --label before-fix        # tag this pass in submitted_by
    python eval/run_claim_suite.py --passes 2                # repeat, for more log volume

Doubles as the Week 11 log-volume generator: every claim run here is a REAL
``react_agent.run()`` call with ``write_trace=True``, so it lands in
``traces/agent_traces.jsonl`` exactly the way a real production request would — nothing in
this file is fabricated to pad the drill's population. ``--label`` and a rotating pool of
fictitious adjuster names go into ``submitted_by`` so repeated passes still produce
distinguishable, searchable rows instead of N identical-looking requests.

Grading is byte-for-byte the same rule every other claim-triage eval in this project uses
(``eval/race.py:grade`` / ``eval/race_multiagent.py:grade``): status must match, and where
gold is PAYABLE the amount must match within a rupee. Copied rather than imported for the
same reason ``eval/race_multiagent.py`` copies it — this file races a different pair of
systems (none; it's a single-system suite) than either of those two.
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import claims_store, react_agent
from src.agent.budgets import Budgets

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 1.0

# Same budget eval/race.py's own RACE_BUDGETS uses, for the same reason: the default
# Budgets() (6,000 max_tokens) is tuned for a single well-behaved call, not a multi-lap
# loop, and cuts a correct run off mid-reasoning — see that file's own comment.
SUITE_BUDGETS = Budgets(max_iterations=12, max_tokens=30_000, max_cost_usd=0.03,
                        max_wall_seconds=200.0)

# Fictitious — this app has no real multi-user concept, so these exist purely to make
# "submitted_by" a real, searchable, varying field across a run instead of a constant.
ADJUSTERS = ["adjuster_priya", "adjuster_karthik", "adjuster_meena", "adjuster_rohit"]


def load_gold() -> dict[str, dict]:
    cases = yaml.safe_load((ROOT / "eval" / "race_cases.yaml").read_text())["cases"]
    return {c["claim_id"]: c for c in cases}


def grade(result: dict, gold: dict) -> bool:
    if result["status"] != gold["status"]:
        return False
    if gold["status"] == "PAYABLE":
        got = result.get("payable_amount")
        if got is None:
            return False
        return abs(float(got) - float(gold["payable_amount"])) <= TOLERANCE
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the full claim suite against gold")
    ap.add_argument("--label", default="", help="tag appended to submitted_by for this pass")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--claims", default="", help="comma-separated claim ids to run instead of all of them")
    ap.add_argument("--model", default=None,
                    help="override GEMINI_MODEL — gemini-3.6-flash's free tier is a "
                         "20-requests-PER-DAY cap (see WEEK11.md's tenx.md), easily "
                         "exhausted by one suite pass; gemini-3.5-flash-lite is a separate "
                         "quota bucket")
    args = ap.parse_args()

    gold = load_gold()
    claim_ids = claims_store.all_claim_ids()
    if args.claims:
        claim_ids = [c.strip() for c in args.claims.split(",") if c.strip()]
    missing = [c for c in claim_ids if c not in gold]
    if missing:
        raise SystemExit(f"race_cases.yaml has no gold answer for: {missing}")

    adjuster_cycle = itertools.cycle(ADJUSTERS)
    rows = []
    for p in range(1, args.passes + 1):
        print(f"\nPASS {p}/{args.passes}")
        for i, claim_id in enumerate(claim_ids, start=1):
            who = next(adjuster_cycle) + (f"_{args.label}" if args.label else "")
            print(f"  {i:>2}/{len(claim_ids)}  {claim_id}  (submitted_by={who}) ...",
                  end="", flush=True)
            result = react_agent.run(claim_id, budgets=SUITE_BUDGETS, submitted_by=who,
                                     model=args.model)
            passed = grade(result, gold[claim_id])
            flag = "PASS" if passed else "FAIL"
            u = result["usage"]
            print(f" {flag}  {result['status']:<11} tokens={u['total_tokens']:<6} "
                  f"${u['cost_usd']:.5f} {u['wall_seconds']:.1f}s")
            rows.append((claim_id, passed, result))
            if args.sleep and not (p == args.passes and i == len(claim_ids)):
                time.sleep(args.sleep)

    n_pass = sum(1 for _, p, _ in rows if p)
    print(f"\n{'='*60}")
    print(f"SUITE RESULT: {n_pass}/{len(rows)} passed")
    print(f"{'='*60}")
    for claim_id, passed, result in rows:
        if not passed:
            print(f"  FAIL  {claim_id}  got {result['status']}/{result.get('payable_amount')}"
                  f"  gold {gold[claim_id]['status']}/{gold[claim_id].get('payable_amount')}")
    return 0 if n_pass == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
