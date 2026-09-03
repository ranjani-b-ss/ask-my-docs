#!/usr/bin/env python
"""THE race. Runs all 10 claims through both systems and reports four comparable numbers
for each: pass rate, p50 latency, total tokens, cost per claim.

    python eval/race.py
    python eval/race.py --skip-agent      # workflow only, for a quick sanity pass
    python eval/race.py --sleep 2.5       # slower between LLM calls, for a tight rate limit

Both systems see exactly the same 10 claim_ids, call exactly the same three tools
(src/agent/tools.py), and are graded against exactly the same gold answers
(eval/race_cases.yaml) with exactly the same rule: status must match, and where the gold
status is PAYABLE the payable_amount must match within a rupee. Nothing about the grading
favours either system.

The embedder and reranker load lazily on first use and cost ~100-200 seconds to warm up —
entirely model-loading, nothing to do with either system being raced. That cost is paid
once, up front, and excluded from every per-claim latency number so claim 1 isn't reported
as 100x slower than claim 2 for a reason that has nothing to do with triage.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import claims_store, react_agent, tools, workflow
from src.agent.budgets import Budgets

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 1.0   # rupees — rounding, never a real disagreement at these amounts


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
    return True   # NOT_PAYABLE / REFERRED: status match is the whole test, see race_cases.yaml



# The default Budgets() (60s wall-clock) is tuned for a *single* well-behaved call, not a
# multi-lap loop against a shared free-tier model whose latency ranged 2-40s per call across
# both smoke runs. At 60s, a perfectly correct 3-4 lap run got cut off before its Final
# Answer — see WEEK7.md for the trace where that happened on C-001 (compute_payout had
# already returned the right number). RACE_BUDGETS gives the loop room to actually finish so
# the race measures reasoning ability, not budget tuning; the deliberately tight budget that
# *is* meant to fire is demonstrated separately in eval/budget_demo.py.
#
# max_tokens raised from 10,000 to 16,000 for the same reason: the payout-verification gate
# added after C-001 (react_agent.py) rejects an unverified Final Answer and forces one more
# lap — a full transcript resend — before accepting a corrected one. That is the gate doing
# its job (see WEEK7.md, claim C-007), but the extra lap has a real token cost, and 10,000
# was measured to be too tight to pay for it on a claim that also needed several
# search_policy calls first.
RACE_BUDGETS = Budgets(max_iterations=8, max_tokens=16_000, max_cost_usd=0.02,
                       max_wall_seconds=150.0)


def run_heat(system: str, claim_ids: list[str], sleep: float) -> list[dict]:
    """Run every claim through one system. One claim's failure does not lose the others.

    This runs after both the workflow decision call and the agent's per-lap call are
    already wrapped against provider errors (see workflow.py and react_agent.py) — this
    try/except is the outermost layer, catching anything neither of those anticipated
    (a bad claim_id, a bug in a tool), so that one unexpected exception costs one row of
    the race, not the whole batch. Earlier development lost a full, successful 10-claim
    workflow heat this way before this layer existed: the agent heat crashed after it, and
    because nothing had been written to disk yet, ``python eval/race.py`` had to be re-run
    from zero rather than resuming.
    """
    rows = []
    for i, claim_id in enumerate(claim_ids, start=1):
        print(f"  [{system:<8}] {i:>2}/{len(claim_ids)}  {claim_id} ...", end="", flush=True)
        try:
            if system == "agent":
                result = react_agent.run(claim_id, budgets=RACE_BUDGETS)
            else:
                result = workflow.run(claim_id)
        except Exception as exc:                       # noqa: BLE001 — isolating one claim
            print(f" ERROR: {exc}")
            result = {
                "system": system, "claim_id": claim_id, "status": "REFERRED",
                "payable_amount": None, "exclusion_clause": None,
                "rationale": f"Unhandled error, not a policy decision: {exc}",
                "stop_reason": f"error: {exc}", "steps": [],
                "usage": {"provider": "-", "model": "-", "llm_calls": 0, "prompt_tokens": 0,
                         "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
                         "wall_seconds": 0.0},
            }
        rows.append(result)
        u = result["usage"]
        print(f" {result['status']:<11} tokens={u['total_tokens']:<6} "
              f"cost=${u['cost_usd']:.5f} {u['wall_seconds']:.1f}s")
        if sleep and i < len(claim_ids):
            time.sleep(sleep)
    return rows


def summarise(system: str, rows: list[dict], gold: dict[str, dict]) -> dict:
    passed = [grade(r, gold[r["claim_id"]]) for r in rows]
    latencies = [r["usage"]["wall_seconds"] for r in rows]
    tokens = [r["usage"]["total_tokens"] for r in rows]
    costs = [r["usage"]["cost_usd"] for r in rows]
    return {
        "system": system,
        "n": len(rows),
        "pass_rate": sum(passed) / len(rows),
        "passed": sum(passed),
        "p50_latency_s": statistics.median(latencies),
        "p90_latency_s": (statistics.quantiles(latencies, n=10)[8]
                          if len(latencies) >= 10 else max(latencies)),
        "total_tokens": sum(tokens),
        "mean_tokens_per_claim": sum(tokens) / len(rows),
        "total_cost_usd": sum(costs),
        "cost_per_claim_usd": sum(costs) / len(rows),
    }


def write_csv(path: Path, agent_rows: list[dict], workflow_rows: list[dict],
             gold: dict[str, dict]) -> None:
    fields = ["system", "claim_id", "status", "payable_amount", "deductible_applied",
              "expected_status", "expected_amount", "pass", "exclusion_clause",
              "stop_reason_or_steps", "llm_calls", "prompt_tokens", "completion_tokens",
              "total_tokens", "cost_usd", "wall_seconds"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for rows in (agent_rows, workflow_rows):
            for r in rows:
                g = gold[r["claim_id"]]
                u = r["usage"]
                writer.writerow({
                    "system": r["system"], "claim_id": r["claim_id"], "status": r["status"],
                    "payable_amount": r.get("payable_amount"),
                    "deductible_applied": r.get("deductible_applied"),
                    "expected_status": g["status"], "expected_amount": g["payable_amount"],
                    "pass": grade(r, g), "exclusion_clause": r.get("exclusion_clause"),
                    "stop_reason_or_steps": r.get("stop_reason") or len(r["steps"]),
                    "llm_calls": u["llm_calls"], "prompt_tokens": u["prompt_tokens"],
                    "completion_tokens": u["completion_tokens"],
                    "total_tokens": u["total_tokens"], "cost_usd": round(u["cost_usd"], 6),
                    "wall_seconds": u["wall_seconds"],
                })


def print_table(agent_summary: dict, workflow_summary: dict) -> None:
    print(f"\n{'='*78}")
    print(f"{'metric':<26} {'agent':>22} {'workflow':>22}")
    print(f"{'-'*26} {'-'*22} {'-'*22}")
    a, w = agent_summary, workflow_summary
    a_pass = f"{a['passed']}/{a['n']} = {a['pass_rate']:.0%}"
    w_pass = f"{w['passed']}/{w['n']} = {w['pass_rate']:.0%}"
    print(f"{'pass rate':<26} {a_pass:>22} {w_pass:>22}")
    print(f"{'p50 latency (s)':<26} {a['p50_latency_s']:>22.2f} {w['p50_latency_s']:>22.2f}")
    print(f"{'total tokens (10 claims)':<26} {a['total_tokens']:>22,} "
          f"{w['total_tokens']:>22,}")
    print(f"{'cost per claim (USD)':<26} {a['cost_per_claim_usd']:>22.5f} "
          f"{w['cost_per_claim_usd']:>22.5f}")
    print(f"{'='*78}")
    print(f"{'  (context) total cost, 10 claims':<26} {a['total_cost_usd']:>22.5f} "
          f"{w['total_cost_usd']:>22.5f}")
    print(f"{'  (context) p90 latency (s)':<26} {a['p90_latency_s']:>22.2f} "
          f"{w['p90_latency_s']:>22.2f}")
    print(f"{'  (context) mean tokens/claim':<26} {a['mean_tokens_per_claim']:>22.1f} "
          f"{w['mean_tokens_per_claim']:>22.1f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Race the agent against the fixed workflow")
    ap.add_argument("--out", default="eval/race.csv")
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--skip-agent", action="store_true")
    ap.add_argument("--skip-workflow", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only the first N claims, for a fast dev loop")
    args = ap.parse_args()

    gold = load_gold()
    claim_ids = claims_store.all_claim_ids()
    if args.limit:
        claim_ids = claim_ids[: args.limit]
    missing = [c for c in claim_ids if c not in gold]
    if missing:
        raise SystemExit(f"race_cases.yaml has no gold answer for: {missing}")

    print(f"warming up the embedder and reranker (one-off, excluded from every "
          f"per-claim number below)...")
    warm_seconds = tools.warm_up()
    print(f"  warm-up took {warm_seconds:.1f}s\n")

    workflow_rows, agent_rows = [], []
    if not args.skip_workflow:
        print(f"HEAT 1 — fixed workflow, {len(claim_ids)} claims")
        workflow_rows = run_heat("workflow", claim_ids, args.sleep)
        # Checkpoint immediately. A crash in heat 2 must not cost a completed heat 1 — that
        # happened once during development (see the docstring on run_heat) and re-running
        # burns real time and real API quota for no reason.
        write_csv(Path("eval/race_workflow_only.csv"), [], workflow_rows, gold)
        print(f"  checkpointed to eval/race_workflow_only.csv\n")
    if not args.skip_agent:
        print(f"HEAT 2 — agent, {len(claim_ids)} claims")
        agent_rows = run_heat("agent", claim_ids, args.sleep)

    if workflow_rows and agent_rows:
        write_csv(Path(args.out), agent_rows, workflow_rows, gold)
        print(f"\nwrote {args.out}")
        print_table(summarise("agent", agent_rows, gold), summarise("workflow", workflow_rows, gold))

        print("\nPER-CLAIM DETAIL")
        print(f"  {'claim':<8} {'gold':<24} {'workflow':<24} {'agent':<24}")
        for cid in claim_ids:
            g = gold[cid]
            w = next(r for r in workflow_rows if r["claim_id"] == cid)
            a = next(r for r in agent_rows if r["claim_id"] == cid)
            gold_s = f"{g['status']}/{g['payable_amount']}"
            w_s = f"{w['status']}/{w.get('payable_amount')}" + ("" if grade(w, g) else " FAIL")
            a_s = f"{a['status']}/{a.get('payable_amount')}" + ("" if grade(a, g) else " FAIL")
            print(f"  {cid:<8} {gold_s:<24} {w_s:<24} {a_s:<24}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
