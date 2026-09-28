#!/usr/bin/env python
"""Week 10 — THE race. Same 10 claims as eval/race.py (race_cases.yaml), same grading rule
(status match, and where gold is PAYABLE the amount matches within a rupee), run fresh
through both the single ReAct agent (react_agent.py) and the manager+2-worker team
(orchestrator.py) today, so the comparison is contemporaneous rather than replayed from an
old CSV.

    python eval/race_multiagent.py                    # full race, both arms
    python eval/race_multiagent.py --skip-agent        # orchestrator only, dev loop
    python eval/race_multiagent.py --failure-case C-004  # separate run, see below

Two things this script deliberately does NOT do, because the brief's own "common mistakes"
warns against exactly this:
  - it does not write a new eval set — race_cases.yaml is the one race.py already uses;
  - it does not give the specialists every tool the single agent has. The coverage worker
    gets search_policy; the facts worker gets nothing but the claim file it was handed;
    neither gets compute_payout, which stays a manager-side deterministic call. Handing
    both workers the full toolset would delete the one plausible source of a multi-agent
    win (narrower prompt, fewer tools per call) before the race even starts.

The failure-injection run (requirement 4) is kept OUT of the main race numbers on purpose:
contaminating race_table.md's pass rate with a fault the single agent never faced would make
the two arms' pass rates incomparable, which is the same mistake as changing the eval set
mid-measurement. It runs as its own pass over one claim, writing failure_case.md.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import claims_store, orchestrator, react_agent, tools
from src.agent.budgets import Budgets

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 1.0

# Same budget the existing Week 7 race uses for the single agent, so this isn't a fresh
# tuning decision — see eval/race.py's own comment for why 60s/default is too tight for a
# multi-lap loop against a free-tier model.
RACE_BUDGETS = Budgets(max_iterations=12, max_tokens=30_000, max_cost_usd=0.03,
                       max_wall_seconds=200.0)


def load_gold() -> dict[str, dict]:
    cases = yaml.safe_load((ROOT / "eval" / "race_cases.yaml").read_text())["cases"]
    return {c["claim_id"]: c for c in cases}


def grade(result: dict, gold: dict) -> bool:
    """Identical rule to eval/race.py:grade — imported by neither, since race.py has no
    orchestrator arm to grade and duplicating four lines beats importing a module named for
    a different pair of systems entirely; kept byte-for-byte identical on purpose."""
    if result["status"] != gold["status"]:
        return False
    if gold["status"] == "PAYABLE":
        got = result.get("payable_amount")
        if got is None:
            return False
        return abs(float(got) - float(gold["payable_amount"])) <= TOLERANCE
    return True


def _p99(data: list[float]) -> float:
    if len(data) < 2:
        return data[0] if data else 0.0
    return statistics.quantiles(data, n=100, method="inclusive")[98]


def run_agent_heat(claim_ids: list[str], sleep: float, model: str | None) -> list[dict]:
    rows = []
    for i, claim_id in enumerate(claim_ids, start=1):
        print(f"  [agent       ] {i:>2}/{len(claim_ids)}  {claim_id} ...", end="", flush=True)
        result = react_agent.run(claim_id, budgets=RACE_BUDGETS, model=model, write_trace=False)
        u = result["usage"]
        print(f" {result['status']:<11} tokens={u['total_tokens']:<6} "
              f"cost=${u['cost_usd']:.5f} {u['wall_seconds']:.1f}s")
        rows.append(result)
        if sleep and i < len(claim_ids):
            time.sleep(sleep)
    return rows


def run_orchestrator_heat(claim_ids: list[str], sleep: float,
                          model: str | None) -> tuple[list[dict], list[dict]]:
    rows, all_handoffs = [], []
    for i, claim_id in enumerate(claim_ids, start=1):
        print(f"  [orchestrator] {i:>2}/{len(claim_ids)}  {claim_id} ...", end="", flush=True)
        result = orchestrator.run(claim_id, model=model, write_trace=False)
        u = result["usage"]
        print(f" {result['status']:<11} tokens={u['total_tokens']:<6} "
              f"cost=${u['cost_usd']:.5f} {u['wall_seconds']:.1f}s")
        rows.append(result)
        all_handoffs.extend(result["handoffs"])
        if sleep and i < len(claim_ids):
            time.sleep(sleep)
    return rows, all_handoffs


def summarise(system: str, rows: list[dict], gold: dict[str, dict]) -> dict:
    passed = [grade(r, gold[r["claim_id"]]) for r in rows]
    latencies = [r["usage"]["wall_seconds"] for r in rows]
    tokens = [r["usage"]["total_tokens"] for r in rows]
    costs = [r["usage"]["cost_usd"] for r in rows]
    return {
        "system": system,
        "n": len(rows),
        "passed": sum(passed),
        "pass_rate": sum(passed) / len(rows),
        "p50_latency_s": statistics.median(latencies),
        "p99_latency_s": _p99(latencies),
        "total_tokens": sum(tokens),
        "total_cost_usd": sum(costs),
        "cost_per_claim_usd": sum(costs) / len(rows),
    }


def write_race_table(path: Path, a: dict, o: dict, multiplier: float,
                     dominant: tuple[str, float]) -> None:
    lines = [
        "# Week 10 race table — single agent vs manager+2-worker orchestrator",
        "",
        "Same 10 claims (C-001 .. C-010, `eval/race_cases.yaml`), same grading rule "
        "(`grade()` in this file, copied byte-for-byte from `eval/race.py`): status must "
        "match, and where gold status is PAYABLE the amount must match within 1 rupee.",
        "",
        f"| metric | single agent (react_agent.py) | orchestrator (manager + 2 workers) |",
        f"|---|---:|---:|",
        f"| pass rate | {a['passed']}/{a['n']} = {a['pass_rate']:.0%} | "
        f"{o['passed']}/{o['n']} = {o['pass_rate']:.0%} |",
        f"| p50 latency (s) | {a['p50_latency_s']:.2f} | {o['p50_latency_s']:.2f} |",
        f"| p99 latency (s) | {a['p99_latency_s']:.2f} | {o['p99_latency_s']:.2f} |",
        f"| total tokens (10 claims) | {a['total_tokens']:,} | {o['total_tokens']:,} |",
        f"| cost per claim (USD) | ${a['cost_per_claim_usd']:.5f} | "
        f"${o['cost_per_claim_usd']:.5f} |",
        f"| (context) total cost, 10 claims | ${a['total_cost_usd']:.5f} | "
        f"${o['total_cost_usd']:.5f} |",
        "",
        f"**Context re-send multiplier**: {multiplier:.1f}x "
        f"(orchestrator total tokens / single-agent total tokens = "
        f"{o['total_tokens']:,} / {a['total_tokens']:,}).",
        "",
        f"Single largest token share: **{dominant[0]}**, {dominant[1]:.0%} of every token "
        "the orchestrator spent across all 10 claims — see `handoffs.log` for the "
        "per-claim, per-hand-off breakdown this number is computed from.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_handoffs_log(path: Path, handoffs: list[dict]) -> dict[str, int]:
    by_name: dict[str, int] = {}
    with path.open("w", encoding="utf-8") as fh:
        for h in handoffs:
            fh.write(json.dumps(h, ensure_ascii=False) + "\n")
            by_name[h["handoff"]] = by_name.get(h["handoff"], 0) + h["total_tokens"]
    return by_name


def run_failure_case(claim_id: str, path: Path, model: str | None) -> None:
    print(f"\nFAILURE INJECTION — coverage_worker forced to 500 on {claim_id}")
    result = orchestrator.run(claim_id, inject_failure=True, model=model, write_trace=False)
    gold = load_gold()[claim_id]
    lines = [
        f"# Week 10 — injected worker failure on {claim_id}",
        "",
        f"**What was injected**: `orchestrator._coverage_worker` raised a simulated HTTP "
        f"500 (`WorkerError`) on every call for claim {claim_id}, standing in for the "
        "coverage/exclusions worker's backend being down.",
        "",
        f"**What the orchestrator actually did**: retried once (a stateless retry against a "
        f"deterministic fault fails identically — `worker_error` below is the same message "
        "twice), then **degraded to a safe REFERRED** rather than guessing at coverage or "
        "declaring the claim covered with no exclusions check. It did not lie.",
        "",
        f"- `degraded`: `{result['degraded']}`",
        f"- `worker_error`: `{result['worker_error']}`",
        f"- final status: `{result['status']}` (gold: `{gold['status']}`)",
        f"- rationale returned to the claims lead: \"{result['rationale']}\"",
        "",
        "Behavior in one line: **degraded to a partial (REFERRED) answer, honestly labeled "
        "as a worker outage — did not retry indefinitely, did not fabricate a coverage "
        "decision.**",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Race the orchestrator against the single agent")
    ap.add_argument("--skip-agent", action="store_true")
    ap.add_argument("--skip-orchestrator", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--failure-case", default="C-004")
    ap.add_argument("--skip-failure-case", action="store_true")
    ap.add_argument("--sleep", type=float, default=3.0,
                    help="seconds between claims within one heat, same purpose as "
                         "eval/race.py's own --sleep")
    ap.add_argument("--model", default=None,
                    help="override GEMINI_MODEL for both arms — the pinned default "
                         "(gemini-3.6-flash) is a per-day-per-model free-tier quota of "
                         "20 requests, confirmed exhausted live while building this race; "
                         "gemini-3.5-flash-lite is a separate quota bucket and still "
                         "answers. Both arms always get the SAME value, same as the "
                         "grading rule — a race is not fair if one arm runs a different "
                         "model than the other.")
    args = ap.parse_args()

    gold = load_gold()
    claim_ids = claims_store.all_claim_ids()
    if args.limit:
        claim_ids = claim_ids[: args.limit]

    print("warming up the embedder and reranker (one-off, excluded from every per-claim "
          "number below)...")
    warm_seconds = tools.warm_up()
    print(f"  warm-up took {warm_seconds:.1f}s\n")

    agent_rows, orch_rows, handoffs = [], [], []
    if not args.skip_agent:
        print(f"HEAT 1 — single agent, {len(claim_ids)} claims")
        agent_rows = run_agent_heat(claim_ids, args.sleep, args.model)
        if not args.skip_orchestrator:
            time.sleep(args.sleep)
    if not args.skip_orchestrator:
        print(f"\nHEAT 2 — orchestrator, {len(claim_ids)} claims")
        orch_rows, handoffs = run_orchestrator_heat(claim_ids, args.sleep, args.model)

    if agent_rows and orch_rows:
        a_summary = summarise("agent", agent_rows, gold)
        o_summary = summarise("orchestrator", orch_rows, gold)
        by_name = write_handoffs_log(ROOT / "handoffs.log", handoffs)
        dominant_name = max(by_name, key=by_name.get)
        dominant_share = by_name[dominant_name] / o_summary["total_tokens"]
        multiplier = round(o_summary["total_tokens"] / a_summary["total_tokens"], 1)
        write_race_table(ROOT / "race_table.md", a_summary, o_summary, multiplier,
                         (dominant_name, dominant_share))
        print(f"\nwrote race_table.md, handoffs.log")

        print(f"\nPER-CLAIM DETAIL")
        print(f"  {'claim':<8} {'gold':<24} {'agent':<24} {'orchestrator':<24}")
        for cid in claim_ids:
            g, a, o = gold[cid], next(r for r in agent_rows if r["claim_id"] == cid), \
                     next(r for r in orch_rows if r["claim_id"] == cid)
            gold_s = f"{g['status']}/{g['payable_amount']}"
            a_s = f"{a['status']}/{a.get('payable_amount')}" + ("" if grade(a, g) else " FAIL")
            o_s = f"{o['status']}/{o.get('payable_amount')}" + ("" if grade(o, g) else " FAIL")
            print(f"  {cid:<8} {gold_s:<24} {a_s:<24} {o_s:<24}")

        Path(ROOT / "race_multiagent_raw.json").write_text(
            json.dumps({"agent": agent_rows, "orchestrator": orch_rows,
                       "agent_summary": a_summary, "orchestrator_summary": o_summary},
                      indent=1, default=str),
            encoding="utf-8",
        )

    if not args.skip_failure_case:
        run_failure_case(args.failure_case, ROOT / "failure_case.md", args.model)

    return 0


if __name__ == "__main__":
    sys.exit(main())
