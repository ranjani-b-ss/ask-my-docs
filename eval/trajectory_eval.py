#!/usr/bin/env python
"""Week 8 — score the PATH the agent took, not just the answer it reached.

    python eval/trajectory_eval.py                                    # score the live trace
    python eval/trajectory_eval.py --trace traces/pre_mitigation_agent_traces.jsonl
    python eval/trajectory_eval.py --before traces/pre_mitigation_agent_traces.jsonl \
                                    --after  traces/agent_traces.jsonl  # regression table

Reads the same agent traces src/agent/react_agent.py already writes (traces/agent_traces.jsonl)
— nothing here re-runs the agent. It only re-reads what a run already did and checks it against
three things a bare pass/fail on the final answer cannot see:

  1. EXPECTED_SEQUENCES     — did the tool calls happen in an order the task actually requires?
  2. argument grounding     — was every claim_id, document_id and deductible figure the model
                              used actually returned by a tool call in THIS run, or invented?
  3. step efficiency        — how many laps did this take against the minimum the fixed
                              workflow (Week 7) needs for the identical task: 5 (get_claim,
                              two search_policy calls, compute_payout, Final Answer)?

The headline number this file exists to produce is the GAP: outcome pass rate minus trajectory
pass rate. A claim can fail zero of the outcome eval's checks and still fail every check in
this file — that gap, not either number alone, is what a claims director should not trust an
agent on.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import claims_store

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 1.0

KNOWN_CLAIM_IDS = set(claims_store.all_claim_ids())

# --------------------------------------------------------------------------------------------
# 1. Expected tool sequences.
#
# Every one of the 10 cases accepts MORE than one valid path, for the same reason a human
# adjuster's own workflow does: the two search_policy calls this task needs — "what is the
# deductible" and "does anything exclude this" — are independent questions with no ordering
# dependency between them, and nothing about doing one before the other changes whether the
# claim is decided correctly. Asserting a single fixed order here would fail a correct run for
# checking the deductible first, which is exactly the brittle-eval mistake Week 8's brief warns
# against. So every case below is asserted as a SUBSEQUENCE requirement, not an exact match:
#
#   get_claim must be the FIRST tool call (rule 1 of the agent's own system prompt).
#   search_policy must appear at least once, anywhere after get_claim and before compute_payout
#     (rule 2 — the exclusion check is mandatory even when nothing in the notes looks risky).
#   compute_payout must appear, and must be the LAST tool call before the Final Answer
#     (rule 8 — the model must never do the subtraction itself).
#
# C-007 is flagged separately: its claim bundles a covered repair with an excluded hire-car
# line item, a genuinely compound question, so it legitimately may need a THIRD search_policy
# call (one for the general exclusion list, one specifically for the hire-car/consequential-loss
# clause) where every other case needs only one. That is the one case-specific extra path this
# eval accepts beyond the uniform three-tool subsequence rule above.
REQUIRED_SUBSEQUENCE = ("get_claim", "search_policy", "compute_payout")

EXPECTED_SEQUENCES = {
    claim_id: {
        "required_subsequence": REQUIRED_SUBSEQUENCE,
        "min_search_calls": 2 if claim_id == "C-007" else 1,
        "note": ("compound claim: general exclusion check AND the hire-car line-item check "
                 "are both legitimate, in either order" if claim_id == "C-007" else
                 "deductible-check and exclusion-check may happen in either order, or be "
                 "combined into fewer/more search_policy calls than exactly two"),
    }
    for claim_id in claims_store.all_claim_ids()
}


def _is_subsequence(needle: tuple[str, ...], haystack: list[str]) -> bool:
    """True if every item in ``needle`` appears in ``haystack`` in order (not necessarily
    contiguous, and other items may appear in between)."""
    it = iter(haystack)
    return all(any(x == n for x in it) for n in needle)


def sequence_check(claim_id: str, tool_names: list[str]) -> tuple[bool, str]:
    """Whether this run's tool-name trajectory satisfies EXPECTED_SEQUENCES[claim_id].

    Returns (passed, reason). ``reason`` explains a failure in the same terms the mentor
    rubric asks for: which required tool never happened, not a generic "sequence mismatch".
    """
    spec = EXPECTED_SEQUENCES[claim_id]
    if not tool_names or tool_names[0] != "get_claim":
        return False, "get_claim was not the first tool call"
    if not _is_subsequence(spec["required_subsequence"], tool_names):
        missing = [t for t in spec["required_subsequence"] if t not in tool_names]
        return False, f"missing required tool(s): {missing}" if missing else \
                      "required tools present but out of order"
    if tool_names[-1] != "compute_payout":
        return False, "compute_payout was not the last tool call before the Final Answer"
    n_search = tool_names.count("search_policy")
    if n_search < spec["min_search_calls"]:
        return False, (f"only {n_search} search_policy call(s), needs "
                        f"{spec['min_search_calls']} ({spec['note']})")
    return True, "ok"


# --------------------------------------------------------------------------------------------
# 2. Argument grounding — "real or fluent fiction".


def _doc_ids_returned(steps: list[dict]) -> set[str]:
    ids: set[str] = set()
    for s in steps:
        if s.get("tool") != "search_policy":
            continue
        try:
            hits = json.loads(s["observation"])
        except (json.JSONDecodeError, TypeError):
            continue
        ids.update(h.get("document_id") for h in hits if h.get("document_id"))
    return ids


def _numbers_returned(steps: list[dict]) -> set[float]:
    """Every numeric figure that actually appeared in a search_policy result's text, so a
    deductible or amount can be checked against what was really retrieved, not assumed."""
    nums: set[float] = set()
    for s in steps:
        if s.get("tool") != "search_policy":
            continue
        try:
            hits = json.loads(s["observation"])
        except (json.JSONDecodeError, TypeError):
            continue
        for h in hits:
            for m in re.findall(r"[\d,]+(?:\.\d+)?", h.get("text", "")):
                try:
                    nums.add(float(m.replace(",", "")))
                except ValueError:
                    pass
    return nums


_DOC_ID_PATTERN = re.compile(r"\b([A-Z]{2,}(?:-[A-Z0-9]+)+)\b")


def argument_check(claim: dict, row: dict) -> tuple[bool, str]:
    """Real inputs, or fluent fiction? Checks three things a model can hallucinate:

    - the claim_id given to get_claim is one that actually exists;
    - the document_id inside any exclusion_clause the Final Answer names was actually
      returned by a search_policy call THIS run — not a plausible-looking id nobody fetched;
    - the deductible figure passed to compute_payout actually appeared in retrieved text.
    """
    steps = row["steps"]
    get_claim_step = next((s for s in steps if s.get("tool") == "get_claim"), None)
    if get_claim_step and get_claim_step.get("tool_args", {}).get("claim_id") not in KNOWN_CLAIM_IDS:
        return False, f"get_claim called with an unknown claim_id: {get_claim_step['tool_args']}"

    doc_ids_seen = _doc_ids_returned(steps)
    exclusion_clause = row.get("exclusion_clause")
    if exclusion_clause:
        cited = set(_DOC_ID_PATTERN.findall(exclusion_clause))
        if not cited:
            return False, f"exclusion_clause {exclusion_clause!r} names no recognisable document id"
        if not cited & doc_ids_seen:
            seen_desc = sorted(doc_ids_seen) if doc_ids_seen else "nothing — search_policy was never called"
            return False, (f"exclusion_clause cites {sorted(cited)}, but search_policy in this "
                           f"run only ever returned {seen_desc}")

    payout_step = next((s for s in steps if s.get("tool") == "compute_payout"), None)
    if payout_step:
        deductible = payout_step.get("tool_args", {}).get("deductible")
        nums_seen = _numbers_returned(steps)
        if deductible and float(deductible) not in nums_seen:
            return False, (f"compute_payout used deductible={deductible}, which never appeared "
                           "in any search_policy result this run")

    return True, "ok"


# --------------------------------------------------------------------------------------------
# 3. Failure-mode taxonomy — the Week 8 "zoo", made checkable.

STEPS_NEEDED = 5   # get_claim, 2x search_policy, compute_payout, Final Answer — the fixed
                   # workflow's own minimum for this identical task (see src/agent/workflow.py)


def classify_modes(claim_id: str, row: dict) -> list[str]:
    """Every failure mode this run exhibits, by name — a run can exhibit more than one."""
    modes = []
    tool_names = [s["tool"] for s in row["steps"] if s.get("tool")]
    seq_ok, seq_reason = sequence_check(claim_id, tool_names)
    if not seq_ok:
        modes.append("skipped_mandatory_tool")   # "giving up quietly"
    arg_ok, arg_reason = argument_check(claims_store.get(claim_id), row)
    if not arg_ok:
        modes.append("fabricated_argument")       # "made-up inputs"
    if tool_names.count("search_policy") >= 3:
        modes.append("redundant_search_loop")     # "loops"
    for s in row["steps"]:
        if s.get("tool") and s["tool"] not in ("get_claim", "search_policy", "compute_payout"):
            modes.append("wrong_tool_choice")      # "wrong tool" — no 4th tool exists to call,
            break                                  # kept as a named, checked-for-and-absent mode
    # A verification gate can be answered honestly (call the tool) or gamed (claim you
    # already did, inside the same turn's own text). "Observation:" only ever enters the
    # transcript because THIS LOOP appended it after a real dispatch — a model turn that
    # contains that word before its own Final Answer is narrating a tool call it never made.
    for s in row["steps"]:
        if (s["parsed"].get("kind") == "final" and s.get("payout_verified") is False
                and "Observation:" in (s.get("raw_output") or "")):
            modes.append("hallucinated_tool_call")
            break
    return modes


# --------------------------------------------------------------------------------------------


def load_agent_rows(trace_path: Path) -> dict[str, dict]:
    """claim_id -> its LAST recorded agent row in this trace file."""
    rows: dict[str, dict] = {}
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["system"] == "agent":
            rows[row["claim_id"]] = row
    return rows


def load_gold() -> dict[str, dict]:
    cases = yaml.safe_load((ROOT / "eval" / "race_cases.yaml").read_text())["cases"]
    return {c["claim_id"]: c for c in cases}


def outcome_pass(row: dict, gold: dict) -> bool:
    if row["status"] != gold["status"]:
        return False
    if gold["status"] == "PAYABLE":
        got = row.get("payable_amount")
        return got is not None and abs(float(got) - float(gold["payable_amount"])) <= TOLERANCE
    return True


def score_trace(trace_path: Path) -> dict:
    gold = load_gold()
    agent_rows = load_agent_rows(trace_path)
    per_claim = {}
    for claim_id in sorted(claims_store.all_claim_ids()):
        row = agent_rows.get(claim_id)
        if row is None:
            per_claim[claim_id] = {"missing": True}
            continue
        tool_names = [s["tool"] for s in row["steps"] if s.get("tool")]
        seq_ok, seq_reason = sequence_check(claim_id, tool_names)
        arg_ok, arg_reason = argument_check(claims_store.get(claim_id), row)
        modes = classify_modes(claim_id, row)
        per_claim[claim_id] = {
            "outcome_pass": outcome_pass(row, gold[claim_id]),
            "sequence_ok": seq_ok, "sequence_reason": seq_reason,
            "argument_ok": arg_ok, "argument_reason": arg_reason,
            "trajectory_pass": seq_ok and arg_ok,
            "iterations": row["iterations"],
            "cost_usd": row["usage"]["cost_usd"],
            "tokens": row["usage"]["total_tokens"],
            "modes": modes,
            "tool_names": tool_names,
        }
    return per_claim


def summarise(per_claim: dict) -> dict:
    scored = {k: v for k, v in per_claim.items() if not v.get("missing")}
    n = len(scored)
    costs = [v["cost_usd"] for v in scored.values()]
    return {
        "n": n,
        "tool_choice_accuracy": sum(v["sequence_ok"] for v in scored.values()) / n,
        "argument_validity_rate": sum(v["argument_ok"] for v in scored.values()) / n,
        "step_efficiency_mean": sum(v["iterations"] for v in scored.values()) / n / STEPS_NEEDED,
        "cost_p50": statistics.median(costs),
        "cost_max": max(costs),
        "outcome_pass_rate": sum(v["outcome_pass"] for v in scored.values()) / n,
        "trajectory_pass_rate": sum(v["trajectory_pass"] for v in scored.values()) / n,
    }


def mode_counts(per_claim: dict) -> dict[str, int]:
    counts: dict[str, int] = {"skipped_mandatory_tool": 0, "fabricated_argument": 0,
                              "redundant_search_loop": 0, "wrong_tool_choice": 0,
                              "hallucinated_tool_call": 0}
    for v in per_claim.values():
        if v.get("missing"):
            continue
        for m in v["modes"]:
            counts[m] = counts.get(m, 0) + 1
    return counts


def print_report(trace_path: Path) -> dict:
    per_claim = score_trace(trace_path)
    summary = summarise(per_claim)

    print(f"\n{'='*88}\nTRAJECTORY EVAL — {trace_path}\n{'='*88}")
    print(f"{'claim':<8} {'outcome':<9} {'sequence':<9} {'args':<7} {'iters':>6} "
          f"{'cost':>10}  tools")
    for cid, v in sorted(per_claim.items()):
        if v.get("missing"):
            print(f"{cid:<8} (no trace recorded)")
            continue
        print(f"{cid:<8} {'PASS' if v['outcome_pass'] else 'FAIL':<9} "
              f"{'ok' if v['sequence_ok'] else 'FAIL':<9} "
              f"{'ok' if v['argument_ok'] else 'FAIL':<7} "
              f"{v['iterations']:>6} ${v['cost_usd']:.5f}  {v['tool_names']}")
        if not v["sequence_ok"]:
            print(f"           sequence: {v['sequence_reason']}")
        if not v["argument_ok"]:
            print(f"           args:     {v['argument_reason']}")

    print(f"\n{'-'*88}")
    print(f"tool-choice accuracy      {summary['tool_choice_accuracy']:.0%} "
          f"({sum(v['sequence_ok'] for v in per_claim.values() if not v.get('missing'))}/"
          f"{summary['n']} correct tool-call sequences)")
    print(f"argument validity rate    {summary['argument_validity_rate']:.0%}")
    print(f"step efficiency (mean)    {summary['step_efficiency_mean']:.2f}"
          f"  (mean laps taken / {STEPS_NEEDED} laps needed — see note below)")
    print(f"cost per claim            p50 ${summary['cost_p50']:.5f}   "
          f"max ${summary['cost_max']:.5f}")
    print(f"\noutcome pass rate         {summary['outcome_pass_rate']:.0%}")
    print(f"trajectory pass rate      {summary['trajectory_pass_rate']:.0%}")
    print(f"GAP (outcome - trajectory) {summary['outcome_pass_rate'] - summary['trajectory_pass_rate']:+.0%}")

    print("\nNOTE on step efficiency: a claim that skips a mandatory tool call finishes in "
          "FEWER laps, so it scores as 'more efficient' by this ratio alone while actually "
          "having done less than required — see the sequence/args columns before trusting "
          "this number on its own.")

    print(f"\n{'-'*88}\nFAILURE-MODE COUNTS (of {summary['n']} claims)")
    for mode, count in mode_counts(per_claim).items():
        print(f"  {mode:<24} {count}")

    return {"per_claim": per_claim, "summary": summary}


def print_regression(before_path: Path, after_path: Path) -> None:
    before = mode_counts(score_trace(before_path))
    after = mode_counts(score_trace(after_path))
    print(f"\n{'='*88}\nREGRESSION — {before_path.name} -> {after_path.name}\n{'='*88}")
    print(f"{'mode':<24} {'before':>8} {'after':>8}  {'change'}")
    all_modes = sorted(set(before) | set(after))
    for mode in all_modes:
        b, a = before.get(mode, 0), after.get(mode, 0)
        flag = ""
        if a > b:
            flag = "  <-- WORSE"
        elif mode not in before and after.get(mode, 0) > 0:
            flag = "  <-- NEW"
        print(f"{mode:<24} {b:>8} {a:>8}  {a - b:+d}{flag}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Score agent trajectories, not just outcomes")
    ap.add_argument("--trace", default="traces/agent_traces.jsonl")
    ap.add_argument("--before", default=None, help="regression mode: the pre-mitigation trace")
    ap.add_argument("--after", default=None, help="regression mode: the post-mitigation trace")
    args = ap.parse_args()

    if args.before and args.after:
        print_regression(ROOT / args.before, ROOT / args.after)
    else:
        print_report(ROOT / args.trace)
    return 0


if __name__ == "__main__":
    sys.exit(main())
