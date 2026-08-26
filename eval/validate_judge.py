#!/usr/bin/env python
"""Measure how far the judge agrees with the hand labels.

    python eval/validate_judge.py --judge v1
    python eval/validate_judge.py --judge v2 --out eval/agreement_v2.json

Runs the judge over exactly the cases in labels_25.json and compares. An unvalidated judge
is a confident number nobody has any reason to trust; this is the step that gives it one, or
takes it away.

Two things are reported and both matter:

  agreement %      how often the judge and the human reached the same verdict
  confusion matrix which DIRECTION the disagreements run

The direction is the part people skip. On this label set 20 of 25 are GROUNDED, so a judge
that answered GROUNDED unconditionally would score 80% — the always-pass baseline is printed
next to the real figure for exactly that reason. And 80% built from false-GROUNDED verdicts
is a judge that waves invented coverage through, while the same 80% built from
false-UNGROUNDED is a judge that is merely irritating. One is a payout, the other is a
second look.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import judge as judge_mod
from src.judge import GROUNDED, UNGROUNDED, agreement

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_evalset import rehydrate

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate the judge against hand labels")
    ap.add_argument("--judge", default="v1")
    ap.add_argument("--labels", default="labels_25.json")
    ap.add_argument("--summaries", default="eval/summaries.json")
    ap.add_argument("--cases", default="eval/claim_cases.yaml")
    ap.add_argument("--out", default=None)
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    label_file = json.loads((ROOT / args.labels).read_text(encoding="utf-8"))
    labels = {k: v["label"] for k, v in label_file["labels"].items()}
    reasons = {k: v["reason"] for k, v in label_file["labels"].items()}

    rows = {r["case_id"]: r for r in
            json.loads((ROOT / args.summaries).read_text(encoding="utf-8"))}
    cases = {c["id"]: c for c in
             yaml.safe_load((ROOT / args.cases).read_text(encoding="utf-8"))["cases"]}

    _, prompt_sha = judge_mod.load_prompt(args.judge)
    print(f"judge     : judge_{args.judge}.txt  sha={prompt_sha}")
    print(f"labels    : {args.labels}  ({len(labels)} hand labels)")
    print(f"human mix : {dict(Counter(labels.values()))}\n")

    verdicts = []
    for i, (case_id, human) in enumerate(sorted(labels.items()), start=1):
        summary = rehydrate(rows[case_id])
        verdict = judge_mod.judge(summary, cases[case_id]["notes"], version=args.judge,
                                  provider=args.provider, model=args.model)
        verdicts.append(verdict)
        mark = "  " if verdict.verdict == human else "!!"
        print(f" {mark} {case_id:<30} human={human:<11} judge={verdict.verdict:<11}"
              + ("" if verdict.verdict == human else f"  {verdict.why[:60]}"))
        if args.sleep and i < len(labels):
            time.sleep(args.sleep)

    report = agreement(labels, verdicts)
    m = report["matrix"]
    n = report["scored"]

    # The number a judge gets for free on a skewed label set.
    majority = Counter(labels.values()).most_common(1)[0]
    baseline = majority[1] / len(labels)

    print(f"\n{'='*84}")
    print(f"AGREEMENT (judge_{args.judge}) : {report['agreed']}/{n} = "
          f"{report['agreement']:.1%}")
    print(f"always-'{majority[0]}' baseline : {majority[1]}/{len(labels)} = {baseline:.1%}"
          f"   <-- beat this or the judge adds nothing")
    print(f"{'='*84}")
    print(f"  both GROUNDED                      {m['both_grounded']}")
    print(f"  both UNGROUNDED                    {m['both_ungrounded']}")
    print(f"  judge GROUNDED, human UNGROUNDED   {m['judge_grounded_human_ungrounded']}"
          f"   <-- judge too lenient: waves invented coverage through")
    print(f"  judge UNGROUNDED, human GROUNDED   {m['judge_ungrounded_human_grounded']}"
          f"   <-- judge too strict: flags summaries that were fine")
    if report["skipped"]:
        print(f"  not scored (judge errored)         {report['skipped']}")

    if report["disagreements"]:
        print(f"\n  DISAGREEMENTS ({len(report['disagreements'])})")
        for d in report["disagreements"]:
            print(f"\n   {d['case_id']}")
            print(f"     human {d['human']}: {reasons[d['case_id']][:150]}")
            print(f"     judge {d['judge']}: {d['judge_why'][:150]}")

    out = Path(args.out or f"eval/agreement_{args.judge}.json")
    out.write_text(json.dumps({
        "judge_version": args.judge,
        "judge_prompt_sha": prompt_sha,
        "labels_file": args.labels,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "agreement": report["agreement"],
        "agreed": report["agreed"],
        "scored": report["scored"],
        "always_majority_baseline": baseline,
        "matrix": m,
        "disagreements": report["disagreements"],
        "verdicts": [{"case_id": v.case_id, "verdict": v.verdict, "why": v.why}
                     for v in verdicts],
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
