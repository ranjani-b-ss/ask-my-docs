#!/usr/bin/env python
"""Deliberately trip a budget and show the agent stop cleanly instead of spinning.

    python eval/budget_demo.py                    # max_iterations=2 on a claim that needs 4+
    python eval/budget_demo.py --budget max_tokens
    python eval/budget_demo.py --budget max_wall_seconds

This is a separate, deliberately artificial run — not part of the race, and not meant to
reflect how the agent is actually configured for real use (see RACE_BUDGETS in race.py for
that). Its only job is to prove the four numbers in src/agent/budgets.py are checked in code,
not just declared: C-010 genuinely needs at least four laps (get_claim, two search_policy
calls for the flood-vs-mechanical-breakdown ambiguity, then a Final Answer), so a budget of
max_iterations=2 is guaranteed to fire before the agent would otherwise finish on its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import react_agent, tools
from src.agent.budgets import Budgets

TIGHT_BUDGETS = {
    "max_iterations": Budgets(max_iterations=2, max_tokens=100_000, max_cost_usd=10.0,
                              max_wall_seconds=600.0),
    "max_tokens": Budgets(max_iterations=100, max_tokens=1500, max_cost_usd=10.0,
                          max_wall_seconds=600.0),
    "max_wall_seconds": Budgets(max_iterations=100, max_tokens=100_000, max_cost_usd=10.0,
                                max_wall_seconds=8.0),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Deliberately trip one budget")
    ap.add_argument("--budget", choices=sorted(TIGHT_BUDGETS), default="max_iterations")
    ap.add_argument("--claim-id", default="C-010",
                    help="a claim needing multiple laps, so the budget fires before a "
                         "natural Final Answer would")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    print(f"warming up...")
    tools.warm_up()

    budgets = TIGHT_BUDGETS[args.budget]
    print(f"\nRunning claim {args.claim_id} with a deliberately tight budget: {budgets}\n")

    result = react_agent.run(args.claim_id, budgets=budgets, write_trace=False)

    print(f"{'='*80}")
    print(f"stop_reason : {result['stop_reason']}")
    print(f"iterations  : {result['iterations']}")
    print(f"final status: {result['status']}  (payable_amount={result['payable_amount']})")
    print(f"usage       : {result['usage']}")
    print(f"{'='*80}\n")

    assert result["stop_reason"].startswith("budget_exceeded"), (
        f"expected a budget to fire, got stop_reason={result['stop_reason']!r} — this claim "
        "finished on its own before the tight budget could prove anything; pick a claim that "
        "genuinely needs more laps, or tighten the budget further"
    )
    assert result["status"] == "REFERRED", (
        "a budget-triggered stop must fail safe to REFERRED, never a guessed PAYABLE/"
        f"NOT_PAYABLE — got status={result['status']!r}"
    )
    print("VERIFIED: the budget fired, the loop stopped, and the result failed safe to "
          "REFERRED rather than guessing or crashing.\n")

    print("FULL STEP LOG")
    for s in result["steps"]:
        print(f"\n--- lap {s['lap']} ---")
        p = s["parsed"]
        if p.get("kind") == "action":
            print(f"  action: {p['tool']}({p['args']})")
            print(f"  observation: {str(s.get('observation'))[:200]}")
        elif p.get("kind") == "final":
            print(f"  FINAL (never reached — the budget fired first): {p['answer']}")
        else:
            print(f"  {p}")
        print(f"  cumulative usage after this lap: {s['cumulative_usage']}")

    out = Path(args.out or f"eval/budget_termination_{args.budget}.json")
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str) + "\n",
                   encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
