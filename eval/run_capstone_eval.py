#!/usr/bin/env python
"""Week 12 — THE integrated eval. One command, 36 cases, through the real entry path.

    python eval/run_capstone_eval.py --model gemini-3.5-flash-lite
    python eval/run_capstone_eval.py --model gemini-3.5-flash-lite --resume     # after a crash
    python eval/run_capstone_eval.py --limit 3                                  # quick check

The cases are the 27 Week 6 claim files plus the 9 Week 12 additions (registry/capstone_claims.yaml:
loss-date boundaries, a lapsed policy, a not-yet-incepted policy, claimant PII, three numbers at
once). Each is run through ``triage_agent`` — the integrated agent over MCP — and scored by
``src/cap_assertions.py``: code first, free and deterministic. The one model-judged criterion is
scored separately by eval/capstone_judge.py against hand labels.

Reported per GROUP, never as one average (the Week 6 rule, and the brief's own common mistake):
the Week 6 mode tags are kept as groups, and the Week 12 additions have groups of their own, so a
regression on the boundary cases cannot hide behind the clean baselines carrying the number.

Checkpoints after every case: a crash on case 31 must not cost the first 30 (it cost a whole
heat once in Week 7, which is why this exists).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import cap_assertions, claim_files, span_log
from src.agent import triage_agent

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "eval" / "capstone_results.json"

CAPSTONE_GROUPS = {
    "CLM-2026-00601": "w12-boundary", "CLM-2026-00602": "w12-boundary",
    "CLM-2026-00607": "w12-boundary", "CLM-2026-00608": "w12-boundary",
    "CLM-2026-00609": "w12-boundary",
    "CLM-2026-00603": "w12-in-force-failure", "CLM-2026-00604": "w12-in-force-failure",
    "CLM-2026-00605": "w12-pii", "CLM-2026-00606": "w12-three-numbers",
}


class OutageStop(Exception):
    """The model provider is down: stop instead of paying the wall-clock budget claim after claim."""


def is_outage(row: dict) -> bool:
    """A run that never got a model reply (0 tokens). It says nothing about the system, so it is never recorded as a result."""
    return row["tokens"] == 0


def case_numbers() -> list[str]:
    idx = claim_files.load_all()
    return sorted(n for n, cf in idx.items() if cf.source in ("week6", "capstone"))


def group_of(cf) -> str:
    return CAPSTONE_GROUPS.get(cf.claim_number) or f"w6-{cf.expect.get('week6_mode', '?')}"


def context_for(result: dict) -> dict:
    trace_id = result["trace_id"]
    trace_row = next((r for r in reversed(span_log.read(span_log.TRACES_FILE))
                      if r.get("trace_id") == trace_id), None)
    referral_id = (result["packet"].get("referral") or {}).get("referral_id")
    referral = next((r for r in reversed(span_log.read(span_log.ROOT / "traces" / "referrals.jsonl"))
                     if r.get("referral_id") == referral_id), None)
    return {"trace_row": trace_row, "referral_record": referral,
            "server_spans": [s for s in span_log.read(span_log.MCP_SPANS_FILE)
                             if s.get("trace_id") == trace_id]}


def score(result: dict) -> dict:
    cf = claim_files.get(result["claim_number"])
    checks = cap_assertions.run_assertions(result, cf, context_for(result))
    u = result["usage"]
    return {
        "claim_number": cf.claim_number, "group": group_of(cf), "product": cf.product,
        "loss_date": cf.loss_date, "trace_id": result["trace_id"],
        "assertions": checks, "all_passed": all(c["passed"] for c in checks.values()),
        "completed": result["stop_reason"] == "final_answer", "stop_reason": result["stop_reason"],
        "laps": result["iterations"], "tokens": u["total_tokens"], "cost_usd": u["cost_usd"],
        "wall_seconds": result["wall_seconds"], "model": u["model"],
        "guard_violations": result["guard_violations"], "overrides": result["overrides"],
        "blocked": result["blocked"], "prompt_version": result["prompt_version"],
        "prompt_sha": result["prompt_sha"], "packet": result["packet"],
    }


def report(rows: list[dict]) -> None:
    n = len(rows)
    print(f"\n{'=' * 92}\nINTEGRATED EVAL — {n} cases   model {rows[0]['model']}   "
          f"prompt {rows[0]['prompt_version']} ({rows[0]['prompt_sha']})\n{'=' * 92}")
    print("\nPASS RATE BY ASSERTION (deterministic, no model involved)")
    for name in cap_assertions.ASSERTION_NAMES:
        p = sum(r["assertions"][name]["passed"] for r in rows)
        print(f"  {name:<30} {p:>3}/{n} = {p / n:>4.0%}")

    print("\nPASS RATE BY GROUP (every assertion must pass)")
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[r["group"]].append(r)
    for g in sorted(groups):
        rs = groups[g]
        p = sum(r["all_passed"] for r in rs)
        print(f"  {g:<30} n={len(rs):>2}  {p:>2}/{len(rs)} = {p / len(rs):>4.0%}")
    total = sum(r["all_passed"] for r in rows)
    print(f"  {'TOTAL':<30} n={n:>2}  {total:>2}/{n} = {total / n:>4.0%}")

    done = sum(r["completed"] for r in rows)
    lat = sorted(r["wall_seconds"] for r in rows)
    cost = sum(r["cost_usd"] for r in rows)
    print("\nRELIABILITY AND COST")
    print(f"  completed with a Final Answer   {done}/{n}  (the rest still ended in a referral)")
    print(f"  attempted outcome statements    {sum(len(r['guard_violations']) for r in rows)}  "
          f"(model tried; the guard replaced them)")
    print(f"  host overrode a model argument  {sum(len(r['overrides']) for r in rows)} time(s) "
          f"across {sum(1 for r in rows if r['overrides'])} case(s)")
    print(f"  tool calls blocked by the gate  {sum(len(r['blocked']) for r in rows)}")
    print(f"  laps per claim                  mean {statistics.mean(r['laps'] for r in rows):.1f}  "
          f"max {max(r['laps'] for r in rows)}")
    print(f"  latency (s)                     p50 {statistics.median(lat):.1f}  "
          f"p99 {lat[min(n - 1, int(0.99 * n))]:.1f}  max {lat[-1]:.1f}")
    print(f"  cost                            ${cost:.4f} total   ${cost / n:.5f} per claim")

    fails = [r for r in rows if not r["all_passed"]]
    if fails:
        print(f"\nFAILURES ({len(fails)})")
        for r in fails:
            for name, c in r["assertions"].items():
                if not c["passed"]:
                    print(f"  {r['claim_number']:<16} [{r['group']}] {name}: {c['detail']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the integrated eval")
    ap.add_argument("--model", default=None)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--claims", default="", help="comma-separated claim numbers to run instead of all 36")
    ap.add_argument("--stop-after-outage", type=int, default=2,
                    help="stop after this many CONSECUTIVE no-reply (quota/outage) claims; they are discarded, not recorded")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--label", default="capstone-eval")
    args = ap.parse_args()

    out_path = Path(args.out)
    done: list[dict] = []
    if args.resume and out_path.exists():
        done = json.loads(out_path.read_text(encoding="utf-8"))
    have = {r["claim_number"] for r in done}
    wanted = [c.strip() for c in args.claims.split(',') if c.strip()] or case_numbers()
    todo = [n for n in wanted if n not in have]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(case_numbers())} cases ({len(have)} already done, {len(todo)} to run)\n")

    rows = list(done)

    outage_run = 0

    def on_result(result: dict) -> None:
        nonlocal outage_run
        row = score(result)
        if is_outage(row):
            outage_run += 1
            print(f"      {row['claim_number']}: no model reply (0 tokens, {row['wall_seconds']:.0f}s) — NOT recorded", flush=True)
            if outage_run >= args.stop_after_outage:
                raise OutageStop(f"{outage_run} consecutive claims got no model reply — provider quota/outage")
            return
        outage_run = 0
        rows.append(row)
        marks = "".join("." if row["assertions"][a]["passed"] else "X"
                        for a in cap_assertions.ASSERTION_NAMES)
        print(f"  {len(rows):>2}/{len(case_numbers())}  {row['claim_number']:<16} {row['group']:<26} "
              f"[{marks}] {'ok ' if row['all_passed'] else 'FAIL'} laps={row['laps']:<2} "
              f"{row['tokens']:>6} tok  ${row['cost_usd']:.5f}  {row['wall_seconds']:>5.1f}s"
              + ("" if row["completed"] else f"  stopped: {row['stop_reason'][:40]}"), flush=True)
        out_path.write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")

    print("assertion order:", ", ".join(cap_assertions.ASSERTION_NAMES), "\n")
    if todo:
        try:
            asyncio.run(triage_agent.run_many(todo, on_result=on_result, model=args.model,
                                              provider=args.provider, submitted_by=args.label))
        except OutageStop as stop:
            print(f"\nSTOPPED EARLY: {stop}. {len(rows)} valid rows are saved in {out_path.name}; re-run with --resume once the "
                  f"quota is back. The no-reply claims were not recorded.", flush=True)
            return 3
    if rows:
        report(rows)
    print(f"\nwrote {out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path}")
    return 0 if rows and all(r["all_passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
