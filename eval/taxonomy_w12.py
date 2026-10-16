"""Week 12 — integrated-system failure taxonomy: counts, from saved traces and results (no model).

Re-scored 2026-10-16 on the final system (v3b: triage-v3 + structured chunking + exclusions gate + parser fix). The v3b
observation sentences were written before counting (taxonomy_w12_notes.md, "Final system" section). The re-score added one mode
(R8) that the first pass had missed in v1 and v2 too, and two mechanical sub-counts (R5 title-only, R4 with the gate search).

Method (same as Week 8): the traces were READ first, one observation sentence each, before any
mode existed (taxonomy_w12_notes.md); modes were named from what was observed; THEN this script
counts them. Census, not a sample: every v1, v2 and v3b run of the 36 eval claims (108 runs).

Five modes are counted mechanically from saved data. Two are HAND-CODED lists, because deciding
them took reading the cited chunk against the prose:
    R2  the citation's clause label is not where the stated fact lives  (HAND_R2)
    R7  an old Week 8 mode recurring: "wording is silent" though an annexure answers  (HAND_R7)
Each hand-coded entry names its trace; R2 candidates were first surfaced mechanically (prose names a
heading that sits INSIDE a cited chunk but is not its label) and then checked by hand.

Primary mode = the highest-priority mode present in a run (the one an adjuster would feel most):
    R4 > R1 > R6 > R7 > R2 > R5 > R3 > R8.   "Runs affected" counts every occurrence, so it overlaps.
R8 is last on purpose: it is counted whenever a number is unresolved, even when the question never asks for it, so it is the
least felt of the modes; ranking it higher would hide R1-R7 behind it.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ("v1", "v2", "v3b")
PRIORITY = ["R4", "R1", "R6", "R7", "R2", "R5", "R3", "R8"]
NAMES = {
    "R4": "Empty packet — loop ends on a budget, no Final Answer, nothing cited",
    "R1": "Superseded clause cited next to its replacement (two conflicting figures)",
    "R6": "Unresolved number (no engine size) not surfaced to the adjuster",
    "R7": "Week 8 mode 1/5 recurring — 'wording is silent' though an annexure holds the answer",
    "R2": "Right chunk, wrong clause label — citation names the chunk's first heading, not where the fact is",
    "R5": "Guard replaces adjuster-facing text with '[withheld: …]'",
    "R3": "Tool call rejected — model echoed the JSON schema as the argument value",
    "R8": "Unresolved co-payment (no age on file) not flagged on the referral — the health twin of R6",
}
NEW = {"R2", "R3", "R5", "R6", "R8"}          # created by joining the pieces, not present in any single week
HAND_R2 = {"v1": ["CLM-2026-00423", "CLM-2026-00491", "CLM-2026-00496", "CLM-2026-00502", "CLM-2026-00584"],
           "v2": ["CLM-2026-00423", "CLM-2026-00502", "CLM-2026-00584", "CLM-2026-00606"],
           "v3b": ["CLM-2026-00423", "CLM-2026-00496", "CLM-2026-00584"]}   # v3b 00606 dropped: its 50% tyre fact is under a correct PW-MOTOR-001 label
HAND_R7 = {"v1": [], "v2": ["CLM-2026-00541"], "v3b": []}


def load():
    traces = {}
    for line in (ROOT / "traces" / "capstone_traces.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        lab = str(r.get("submitted_by", ""))
        if lab in tuple(f"capstone-eval-{v}" for v in VERSIONS) and r["usage"]["total_tokens"] > 0 \
                and "max_wall" not in str(r["stop_reason"]):
            traces[(lab.removeprefix("capstone-eval-"), r["claim_number"])] = r
    results = {v: {r["claim_number"]: r for r in json.loads((ROOT / "eval" / f"capstone_results_{v}.json").read_text())}
               for v in VERSIONS}
    return traces, results


def referral_flags() -> dict:
    """trace_id -> flags on the first referral record written for that trace."""
    out = {}
    for line in (ROOT / "traces" / "referrals.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        out.setdefault(r["trace_id"], r.get("flags") or [])
    return out


TITLE = re.compile(r"not covered|uncovered", re.I)


def final_text(trace) -> str:
    raw = " ".join(str(s.get("raw_output") or s.get("raw") or "") for s in trace["steps"])
    return raw[raw.rfind("Final Answer"):] if "Final Answer" in raw else raw


def title_only(trace) -> bool:
    """R5 sub-count: every guard hit is the word 'covered', and in the model's final text that word
    occurs only inside the clause title 'What is not covered' (the guard matched a heading, not an outcome)."""
    hits = {w for v in trace["guard_violations"] for w in v.get("matched", [])}
    if hits != {"covered"}:
        return False
    return "covered" not in re.sub(TITLE, "", final_text(trace)).lower()


def flags(v, claim, trace, results, rflags):
    p, a = trace["packet"], results[v][claim]["assertions"]
    shown = json.dumps({k: p[k] for k in ("summary_for_adjuster", "facts")}) + str(p["referral"].get("reason"))
    f = set()
    if str(trace["stop_reason"]).startswith("budget"):
        f.add("R4")
    if not a["superseded_not_cited"]["passed"]:
        f.add("R1")
    if not a["numbers_distinct_and_correct"]["passed"] and "unresolved" in a["numbers_distinct_and_correct"]["detail"]:
        f.add("R6")
    if claim in HAND_R7[v]:
        f.add("R7")
    if claim in HAND_R2[v]:
        f.add("R2")
    if "[withheld" in shown:
        f.add("R5")
    if any(s.get("kind") == "tool" and s.get("ok") is False and not s.get("blocked") for s in trace["spans"]):
        f.add("R3")
    cp = (p.get("numbers") or {}).get("co_payment") or {}
    if cp.get("needs") and cp.get("applies") is None and not any(str(x).startswith("unresolved:co_payment") for x in rflags.get(trace["trace_id"], [])):
        f.add("R8")
    return f


def main() -> dict:
    traces, results = load()
    rf = referral_flags()
    out = {}
    for v in VERSIONS:
        rows = {c: flags(v, c, t, results, rf) for (vv, c), t in traces.items() if vv == v}
        primary = {c: next((m for m in PRIORITY if m in f), None) for c, f in rows.items()}
        r5 = [c for c, f in rows.items() if "R5" in f]
        out[v] = {"n": len(rows),
                  "affected": {m: sorted(c for c, f in rows.items() if m in f) for m in PRIORITY},
                  "primary": {m: sorted(c for c, p in primary.items() if p == m) for m in PRIORITY},
                  "no_failure": sorted(c for c, p in primary.items() if p is None),
                  "r5_title_only": sorted(c for c in r5 if title_only(traces[(v, c)])),
                  "budget_stops_with_gate_search": sorted(c for c, f in rows.items() if "R4" in f and any(
                      re.search(r'"query":\s*"[^"]*not covered', str(st.get("raw_output")), re.I)
                      for st in traces[(v, c)]["steps"])),
                  "trace_ids": {c: traces[(v, c)]["trace_id"] for c in rows}}
    (ROOT / "eval" / "taxonomy_w12.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{'mode':<4}{'affected v1':>12}{'v2':>5}{'v3b':>5}{'primary v1':>12}{'v2':>5}{'v3b':>5}   new?  description")
    for m in PRIORITY:
        a = [len(out[v]["affected"][m]) for v in VERSIONS]
        pr = [len(out[v]["primary"][m]) for v in VERSIONS]
        print(f"{m:<4}{a[0]:>12}{a[1]:>5}{a[2]:>5}{pr[0]:>12}{pr[1]:>5}{pr[2]:>5}   {'NEW ' if m in NEW else '    '}  {NAMES[m]}")
    print(f"{'none':<4}{'':>12}{'':>5}{'':>5}" + "".join(f"{len(out[v]['no_failure']):>{w}}" for v, w in zip(VERSIONS, (12, 5, 5))))
    for v in VERSIONS:
        print(v, "runs with any mode:", out[v]["n"] - len(out[v]["no_failure"]), "| R5 title-only:", len(out[v]["r5_title_only"]),
              "of", len(out[v]["affected"]["R5"]), "| R4 with gate search:", len(out[v]["budget_stops_with_gate_search"]), "of", len(out[v]["affected"]["R4"]))
    return out


if __name__ == "__main__":
    main()
