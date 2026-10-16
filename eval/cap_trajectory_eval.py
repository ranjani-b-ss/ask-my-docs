"""Week 12 — trajectory eval, scored offline from saved host traces (no model, no MCP).

The outcome assertions in run_capstone_eval.py ask "is the packet right?". This asks "did the agent
get there by the right route?" — and reports the two together, because the gap between them is the
finding: a run can hand the adjuster a correct packet after calling a tool with an invalid argument,
or after the code blocked a premature referral. The packet hides that; the trajectory does not.

GOLD is derived from the registry (is the policy in force on the loss date?) and never from the run:
  in force      lookup_policy -> check_in_force -> search_wording (>=1) -> get_limits -> refer_to_adjuster
  not in force  lookup_policy -> check_in_force -> refer_to_adjuster      (search_wording, get_limits forbidden)

Per trace:
  tool_choice_accuracy   of every tool call the MODEL attempted, the share that was a permitted tool,
                         was not blocked by the gate and did not fail validation
  trajectory_clean       required tools all ran, no forbidden tool ran, order respected, and zero
                         blocked or failed attempts
  extra_calls            attempts beyond the minimal route
Outcome-vs-trajectory gap: outcome passed (all deterministic assertions) but trajectory not clean.

Order, forbidden tools and required tools are ENFORCED by the gate in code, so those three cannot
fail on a finished run; what the model can still get wrong is blocked and invalid calls and wasted
searches. Reported as such — a trajectory score that is 100% by construction is not a result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import registry                                   # noqa: E402

IN_FORCE_ROUTE = ["lookup_policy", "check_in_force", "search_wording", "get_limits", "refer_to_adjuster"]
LAPSED_ROUTE = ["lookup_policy", "check_in_force", "refer_to_adjuster"]
FORBIDDEN_WHEN_LAPSED = {"search_wording", "get_limits"}


def gold_for(claim_number: str, loss_date: str) -> dict:
    policy = registry.policy_for_claim(claim_number)
    in_force = bool(policy) and registry.check_in_force(policy["policy_number"], loss_date)["in_force"]
    route = IN_FORCE_ROUTE if in_force else LAPSED_ROUTE
    return {"in_force": in_force, "route": route,
            "forbidden": set() if in_force else FORBIDDEN_WHEN_LAPSED}


def attempts(trace: dict) -> list[dict]:
    """Every tool call the model asked for, in order: executed, blocked by the gate, or rejected."""
    out = []
    for sp in trace.get("spans") or []:
        if sp.get("source") != "host" or sp.get("kind") != "tool":
            continue
        out.append({"tool": sp.get("tool"), "blocked": bool(sp.get("blocked")),
                    "failed": sp.get("ok") is False and not sp.get("blocked")})
    return out


def score_trajectory(trace: dict, gold: dict) -> dict:
    calls = attempts(trace)
    ran = [c["tool"] for c in calls if not c["blocked"] and not c["failed"]]
    permitted = set(gold["route"])
    good = [c for c in calls if c["tool"] in permitted and c["tool"] not in gold["forbidden"]
            and not c["blocked"] and not c["failed"]]
    first = {t: ran.index(t) for t in set(ran)}
    in_order = all(first[a] < first[b] for a, b in zip(gold["route"], gold["route"][1:])
                   if a in first and b in first)
    missing = [t for t in gold["route"] if t not in ran]
    forbidden_ran = sorted(set(ran) & gold["forbidden"])
    blocked = sum(c["blocked"] for c in calls)
    failed = sum(c["failed"] for c in calls)
    clean = not missing and not forbidden_ran and in_order and not blocked and not failed
    return {"attempts": len(calls), "tool_choice_accuracy": (len(good) / len(calls)) if calls else None,
            "blocked": blocked, "failed": failed, "missing": missing, "forbidden_ran": forbidden_ran,
            "in_order": in_order, "extra_calls": max(0, len(calls) - len(gold["route"])),
            "trajectory_clean": clean}


def evaluate(traces: list[dict], outcomes: dict[str, bool]) -> dict:
    rows = []
    for t in traces:
        gold = gold_for(t["claim_number"], t["packet"]["loss_date"] if t.get("packet") else
                        _loss_date(t["claim_number"]))
        s = score_trajectory(t, gold)
        rows.append({"claim_number": t["claim_number"], "trace_id": t["trace_id"],
                     "gold_route": "in_force" if gold["in_force"] else "lapsed",
                     "outcome_ok": outcomes.get(t["claim_number"]), **s})
    n = len(rows)
    acc_num = sum(r["tool_choice_accuracy"] * r["attempts"] for r in rows if r["attempts"])
    acc_den = sum(r["attempts"] for r in rows)
    clean = sum(r["trajectory_clean"] for r in rows)
    ok_not_clean = [r["claim_number"] for r in rows if r["outcome_ok"] and not r["trajectory_clean"]]
    clean_not_ok = [r["claim_number"] for r in rows if not r["outcome_ok"] and r["trajectory_clean"]]
    return {"n": n, "tool_choice_accuracy": acc_num / acc_den if acc_den else None,
            "trajectory_clean": clean, "outcome_ok": sum(bool(r["outcome_ok"]) for r in rows),
            "outcome_ok_but_trajectory_not_clean": ok_not_clean,
            "trajectory_clean_but_outcome_failed": clean_not_ok,
            "lapsed_gold_cases": sum(r["gold_route"] == "lapsed" for r in rows), "rows": rows}


def _loss_date(claim_number: str) -> str:
    from src import claim_files
    return claim_files.get(claim_number).loss_date


def load(label: str, results_path: Path) -> tuple[list[dict], dict[str, bool]]:
    results = {r["claim_number"]: r for r in json.loads(results_path.read_text(encoding="utf-8"))}
    traces = {}
    for line in (ROOT / "traces" / "capstone_traces.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("submitted_by") == label and row["claim_number"] in results:
            traces[row["claim_number"]] = row            # latest wins; a resumed case supersedes
    outcomes = {n: bool(results[n]["all_passed"]) for n in traces}
    return list(traces.values()), outcomes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    traces, outcomes = load(a.label, Path(a.results))
    rep = evaluate(traces, outcomes)
    print(f"TRAJECTORY EVAL — {a.label}   n={rep['n']}   (gold from the registry, not from the run)")
    print(f"  tool-choice accuracy        {rep['tool_choice_accuracy']:.1%} of attempted calls")
    print(f"  trajectory clean            {rep['trajectory_clean']}/{rep['n']}")
    print(f"  outcome assertions passed   {rep['outcome_ok']}/{rep['n']}")
    print(f"  right packet, wrong route   {len(rep['outcome_ok_but_trajectory_not_clean'])}: "
          f"{', '.join(rep['outcome_ok_but_trajectory_not_clean']) or '-'}")
    print(f"  clean route, failed packet  {len(rep['trajectory_clean_but_outcome_failed'])}: "
          f"{', '.join(rep['trajectory_clean_but_outcome_failed']) or '-'}")
    print(f"  cases whose gold route is the LAPSED one: {rep['lapsed_gold_cases']} of {rep['n']}")
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=2, default=list), encoding="utf-8")
        print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
