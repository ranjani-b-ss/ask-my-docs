"""Week 12 — integrated-system failure taxonomy: counts, from saved traces and results (no model).

Method (same as Week 8): the traces were READ first, one observation sentence each, before any
mode existed (taxonomy_w12_notes.md); modes were named from what was observed; THEN this script
counts them. Census, not a sample: every v1 and v2 run of the 36 eval claims (72 runs).

Five modes are counted mechanically from saved data. Two are HAND-CODED lists, because deciding
them took reading the cited chunk against the prose:
    R2  the citation's clause label is not where the stated fact lives  (HAND_R2)
    R7  an old Week 8 mode recurring: "wording is silent" though an annexure answers  (HAND_R7)
Each hand-coded entry names its trace; R2 candidates were first surfaced mechanically (prose names a
heading that sits INSIDE a cited chunk but is not its label) and then checked by hand.

Primary mode = the highest-priority mode present in a run (the one an adjuster would feel most):
    R4 > R1 > R6 > R7 > R2 > R5 > R3.   "Runs affected" counts every occurrence, so it overlaps.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIORITY = ["R4", "R1", "R6", "R7", "R2", "R5", "R3"]
NAMES = {
    "R4": "Empty packet — loop ends on a budget, no Final Answer, nothing cited",
    "R1": "Superseded clause cited next to its replacement (two conflicting figures)",
    "R6": "Unresolved number (no engine size) not surfaced to the adjuster",
    "R7": "Week 8 mode 1/5 recurring — 'wording is silent' though an annexure holds the answer",
    "R2": "Right chunk, wrong clause label — citation names the chunk's first heading, not where the fact is",
    "R5": "Guard replaces adjuster-facing text with '[withheld: …]'",
    "R3": "Tool call rejected — model echoed the JSON schema as the argument value",
}
NEW = {"R2", "R3", "R5", "R6"}          # created by joining the pieces, not present in any single week
HAND_R2 = {"v1": ["CLM-2026-00423", "CLM-2026-00491", "CLM-2026-00496", "CLM-2026-00502", "CLM-2026-00584"],
           "v2": ["CLM-2026-00423", "CLM-2026-00502", "CLM-2026-00584", "CLM-2026-00606"]}
HAND_R7 = {"v1": [], "v2": ["CLM-2026-00541"]}


def load():
    traces = {}
    for line in (ROOT / "traces" / "capstone_traces.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        lab = str(r.get("submitted_by", ""))
        if lab in ("capstone-eval-v1", "capstone-eval-v2") and r["usage"]["total_tokens"] > 0 \
                and "max_wall" not in str(r["stop_reason"]):
            traces[(lab[-2:], r["claim_number"])] = r
    results = {v: {r["claim_number"]: r for r in json.loads((ROOT / "eval" / f"capstone_results_{v}.json").read_text())}
               for v in ("v1", "v2")}
    return traces, results


def flags(v, claim, trace, results):
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
    return f


def main() -> dict:
    traces, results = load()
    out = {}
    for v in ("v1", "v2"):
        rows = {c: flags(v, c, t, results) for (vv, c), t in traces.items() if vv == v}
        primary = {c: next((m for m in PRIORITY if m in f), None) for c, f in rows.items()}
        out[v] = {"n": len(rows),
                  "affected": {m: sorted(c for c, f in rows.items() if m in f) for m in PRIORITY},
                  "primary": {m: sorted(c for c, p in primary.items() if p == m) for m in PRIORITY},
                  "no_failure": sorted(c for c, p in primary.items() if p is None),
                  "trace_ids": {c: traces[(v, c)]["trace_id"] for c in rows}}
    (ROOT / "eval" / "taxonomy_w12.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{'mode':<4}{'affected v1':>12}{'v2':>5}{'primary v1':>12}{'v2':>5}   new?  description")
    for m in PRIORITY:
        print(f"{m:<4}{len(out['v1']['affected'][m]):>12}{len(out['v2']['affected'][m]):>5}"
              f"{len(out['v1']['primary'][m]):>12}{len(out['v2']['primary'][m]):>5}   {'NEW ' if m in NEW else '    '}  {NAMES[m]}")
    print(f"{'none':<4}{'':>12}{'':>5}{len(out['v1']['no_failure']):>12}{len(out['v2']['no_failure']):>5}")
    return out


if __name__ == "__main__":
    main()
