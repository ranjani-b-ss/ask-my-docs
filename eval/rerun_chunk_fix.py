#!/usr/bin/env python
"""Week 11 follow-up — re-run the two cases the chunk boundary broke (C-007, C-011), with the repair attributed.

    python eval/rerun_chunk_fix.py --runs 2

C-011 (outside-India collision) and C-007 (hire-car bill) both depend on the tail of the motor exclusion list, which the
`recursive` chunker left in a stub chunk. Three arms, everything else identical (prompt v3 — NO clause wording in it —,
model, budgets, claims, grader):
    A  old chunks (recursive_800_150), exclusions gate OFF   = the leak removed, nothing repaired
    B  new chunks (structured_800_150), gate OFF             = the chunk repair alone
    C  new chunks, gate ON                                   = the chunk repair + the gate (the shipped configuration)

DEFINITIONS, written before any run:
  PASS      the suite's own grader (eval/run_claim_suite.grade) against eval/race_cases.yaml gold:
            C-011 NOT_PAYABLE; C-007 PAYABLE 33,000.
  EXPOSED   the governing bullet's text appeared in a search observation this run (the model was shown it).
            C-011: 'outside the geographical area stated in the schedule'; C-007: 'hire charges for a\\n  replacement vehicle'.
Arms are interleaved case by case so a quota stop cannot favour one. One run per cell is a sample of a stochastic system:
report counts out of n.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import run_claim_suite as rcs                                           # noqa: E402
from src.agent import react_agent                                        # noqa: E402

CASES = ["C-011", "C-007"]
MARK = {"C-011": "outside the geographical area stated in the schedule", "C-007": "hire charges for a\n  replacement vehicle"}
ARMS = {"A": {"AGENT_CHUNKING": "recursive_800_150", "AGENT_EXCLUSIONS_GATE": "off"},
        "B": {"AGENT_CHUNKING": "structured_800_150", "AGENT_EXCLUSIONS_GATE": "off"},
        "C": {"AGENT_CHUNKING": "structured_800_150", "AGENT_EXCLUSIONS_GATE": "on"}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--out", default=str(ROOT / "eval" / "chunk_fix_rerun.json"))
    a = ap.parse_args()
    out = Path(a.out)
    rows = json.loads(out.read_text()) if out.exists() else []
    done = {(r["case"], r["arm"], r["run"]) for r in rows}
    gold = rcs.load_gold()
    for run in range(1, a.runs + 1):
        for case in CASES:
            for arm, env in ARMS.items():
                if (case, arm, run) in done:
                    continue
                os.environ.update(env)
                res = react_agent.run(case, budgets=rcs.SUITE_BUDGETS, submitted_by=f"chunkfix-{arm}", model=a.model)
                seen = [s.get("observation") or "" for s in res["steps"] if s.get("tool") == "search_policy"]
                row = {"case": case, "arm": arm, "run": run, "status": res["status"],
                       "payable_amount": res.get("payable_amount"), "passed": rcs.grade(res, gold[case]),
                       "exposed": any(MARK[case] in o.replace("\\n", "\n") for o in seen),
                       "exclusions_read": any(s.get("exclusions_read") for s in res["steps"]),
                       "stop_reason": res["stop_reason"], "laps": res["iterations"],
                       "tokens": res["usage"]["total_tokens"], "cost_usd": res["usage"]["cost_usd"],
                       "prompt_version": res["prompt_version"], "prompt_sha": res["prompt_sha"]}
                rows.append(row)
                out.write_text(json.dumps(rows, indent=1))
                print(f"{case} run{run} arm {arm}: {'PASS' if row['passed'] else 'FAIL'} {row['status']:<11} "
                      f"exposed={row['exposed']!s:<5} laps={row['laps']} tok={row['tokens']} stop={row['stop_reason'][:28]}",
                      flush=True)
                time.sleep(2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
