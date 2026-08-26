#!/usr/bin/env python
"""THE one command. Scores every claim summary and prints the pass rate by mode.

    python eval/run_evalset.py                        # assertions + judge v1
    python eval/run_evalset.py --judge v2             # after the iteration
    python eval/run_evalset.py --no-judge             # assertions only, free and offline
    python eval/run_evalset.py --regenerate           # re-write the summaries first

Reports per mode, never as one average. A single overall pass rate is the most comfortable
number available and the least useful: on this eval set the four controls and the six
condition cases between them can hold the average up while the exclusion-citation cases
collapse, and the average would not move enough to notice. The taxonomy exists precisely so
that a regression has somewhere to show up.

Order of scoring, which is also the order of cost:

    4 deterministic assertions   free, offline, identical every run
    1 judged criterion           one model call per case, validated against hand labels

The judge is asked about one thing only. Everything a regex can decide was moved out of the
prompt (see src/assertions.py and the judge_v0 -> judge_v1 diff).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.assertions import ASSERTION_NAMES, citations_resolve, run_assertions
from src.config import DEFAULT_CHUNKING
from src.summariser import Summary
from src import judge as judge_mod
from src import store

ROOT = Path(__file__).resolve().parent.parent
SUMMARIES = ROOT / "eval" / "summaries.json"


def load_summaries(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"No summaries at {path}. Run: python eval/make_summaries.py")
    return json.loads(path.read_text(encoding="utf-8"))


def rehydrate(row: dict) -> Summary:
    """Rebuild a Summary from the stored artefact, including its retrieved passages.

    The passage TEXT is fetched from the store by chunk_id rather than duplicated into
    summaries.json. Same discipline as the Week 5 traces: one source of truth for chunk text,
    and a stored id that proves which passage was used.
    """
    from src.config import ChunkConfig
    from src.retriever import Hit

    collection = store.get_collection(DEFAULT_CHUNKING, row["corpus"])
    ids = [h["chunk_id"] for h in row["retrieved"]]
    fetched = store.get_by_ids(collection, ids)
    hits = [
        Hit(text=fetched[h["chunk_id"]]["text"], meta=fetched[h["chunk_id"]]["meta"],
            cosine=h["cosine"], chunk_id=h["chunk_id"], rerank_score=h.get("rerank"))
        for h in row["retrieved"] if h["chunk_id"] in fetched
    ]
    return Summary(row["case_id"], row["summary"], row["fields"], hits,
                   bool(row["summary"]), row["mode_of_generation"], row["reason"],
                   row["query"])


def main() -> int:
    ap = argparse.ArgumentParser(description="Score the claim-summary eval set")
    ap.add_argument("--cases", default="eval/claim_cases.yaml")
    ap.add_argument("--summaries", default=str(SUMMARIES))
    ap.add_argument("--judge", default="v1", help="judge prompt version, or 'none'")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--out", default="eval/results.json")
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    cases = {c["id"]: c for c in
             yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))["cases"]}
    rows = load_summaries(Path(args.summaries))
    use_judge = not args.no_judge and args.judge != "none"

    if use_judge:
        _, judge_sha = judge_mod.load_prompt(args.judge)
        print(f"judge     : judge_{args.judge}.txt  sha={judge_sha}")
    print(f"cases     : {len(rows)}   assertions: {len(ASSERTION_NAMES)}   "
          f"judged criteria: {1 if use_judge else 0}")
    print(f"summaries : {args.summaries}\n")

    results = []
    for i, row in enumerate(rows, start=1):
        case = cases[row["case_id"]]
        summary = rehydrate(row)
        checks = run_assertions(summary, case)
        cite = citations_resolve(summary)

        verdict = None
        if use_judge:
            verdict = judge_mod.judge(summary, case["notes"], version=args.judge,
                                      provider=args.provider, model=args.model)
            if args.sleep and i < len(rows):
                time.sleep(args.sleep)

        assertions_passed = all(c.passed for c in checks)
        judged_passed = verdict.passed if verdict else None
        overall = assertions_passed and (judged_passed is not False)

        results.append({
            "case_id": row["case_id"],
            "mode": row["mode"],
            "regression_of": row.get("regression_of"),
            "position": summary.get("position"),
            "assertions": {c.name: {"passed": c.passed, "detail": c.detail} for c in checks},
            "assertions_passed": assertions_passed,
            "citations_resolve": {"passed": cite.passed, "detail": cite.detail},
            "judge": ({"verdict": verdict.verdict, "why": verdict.why,
                       "version": verdict.prompt_version, "sha": verdict.prompt_sha}
                      if verdict else None),
            "judged_passed": judged_passed,
            "passed": overall,
        })

        flag = "  " if overall else "! "
        jv = (verdict.verdict[:10] if verdict else "-")
        failed = [c.name for c in checks if not c.passed]
        print(f" {flag}{row['case_id']:<30} {row['mode']:<26} "
              f"A:{sum(c.passed for c in checks)}/{len(checks)} J:{jv:<11}"
              + (f"  <- {', '.join(failed)}" if failed else ""))

    # ------------------------------------------------------------------ per-mode table
    by_mode: dict[str, list] = defaultdict(list)
    for r in results:
        by_mode[r["mode"]].append(r)

    print(f"\n{'='*94}")
    print("PASS RATE BY MODE")
    print(f"{'='*94}")
    print(f"  {'mode':<28} {'n':>3}  {'assertions':>12}  {'judged':>12}  {'overall':>12}")
    print(f"  {'-'*28} {'-'*3}  {'-'*12}  {'-'*12}  {'-'*12}")
    for mode in sorted(by_mode):
        group = by_mode[mode]
        n = len(group)
        a = sum(1 for r in group if r["assertions_passed"])
        j_scored = [r for r in group if r["judged_passed"] is not None]
        j = sum(1 for r in j_scored if r["judged_passed"])
        o = sum(1 for r in group if r["passed"])
        j_cell = f"{j}/{len(j_scored)} = {j/len(j_scored):.0%}" if j_scored else "—"
        print(f"  {mode:<28} {n:>3}  {a}/{n} = {a/n:>4.0%}  {j_cell:>12}  "
              f"{o}/{n} = {o/n:>4.0%}")

    n = len(results)
    a = sum(1 for r in results if r["assertions_passed"])
    j_scored = [r for r in results if r["judged_passed"] is not None]
    j = sum(1 for r in j_scored if r["judged_passed"])
    o = sum(1 for r in results if r["passed"])
    print(f"  {'-'*28} {'-'*3}  {'-'*12}  {'-'*12}  {'-'*12}")
    jt = f"{j}/{len(j_scored)} = {j/len(j_scored):.0%}" if j_scored else "—"
    print(f"  {'TOTAL':<28} {n:>3}  {a}/{n} = {a/n:>4.0%}  {jt:>12}  {o}/{n} = {o/n:>4.0%}")

    # ------------------------------------------------------- per-assertion breakdown
    print(f"\n  ASSERTION BREAKDOWN (deterministic, no model involved)")
    for name in ASSERTION_NAMES:
        passed = sum(1 for r in results if r["assertions"][name]["passed"])
        print(f"    {name:<28} {passed}/{n} = {passed/n:>4.0%}")
    cites = sum(1 for r in results if r["citations_resolve"]["passed"])
    print(f"    {'citations_resolve':<28} {cites}/{n} = {cites/n:>4.0%}   (pre-existing check)")

    regressions = [r for r in results if r["regression_of"]]
    if regressions:
        print(f"\n  REGRESSION CASES (replayed from real failed traces)")
        for r in regressions:
            print(f"    {r['case_id']:<30} from {r['regression_of']}  "
                  f"{'PASS' if r['passed'] else 'FAIL'}")

    Path(args.out).write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    print(f"\n  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
