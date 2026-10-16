"""Week 12 — judge agreement on the 36 final-system (v3b) outputs. Offline; reads saved judge verdicts.

    python eval/cap_judge_v3b_report.py eval/cap_judge_v1_v3b.json

All 36 hand labels are GROUNDED (eval/labels_cap_v3b.json, hashed before the judge ran), so this measures one thing only:
how often the frozen judge raises a false alarm on a grounded output. It cannot measure recall — there is no ungrounded
natural output to catch; recall on planted errors is the v1/v2 measurement and was not repeated.
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cap_judge_agreement import majority, wilson          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main(path: str) -> dict:
    res = json.loads(Path(path).read_text())
    labels = json.loads((ROOT / "eval" / "labels_cap_v3b.json").read_text())["labels"]
    rows, flips, errors = {}, [], 0
    for key, lab in labels.items():
        runs = res.get(f"natural:{key}", {}).get("runs", [])
        errors += sum(r["verdict"] == "ERROR" for r in runs)
        v = majority(runs)
        rows[key] = {"label": lab["label"], "judge": v, "runs": [r["verdict"][:1] for r in runs]}
        if len({r["verdict"] for r in runs if r["verdict"] != "ERROR"}) > 1:
            flips.append(key)
    scored = {k: r for k, r in rows.items() if r["judge"] in ("GROUNDED", "UNGROUNDED")}
    agree = sum(r["judge"] == r["label"] for r in scored.values())
    fa = sorted(k for k, r in scored.items() if r["judge"] == "UNGROUNDED")
    lo, hi = wilson(agree, len(scored))
    out = {"n_labelled": len(rows), "n_scored": len(scored), "agreement": agree, "agreement_pct": round(100 * agree / len(scored), 1),
           "wilson_95": [round(100 * lo, 1), round(100 * hi, 1)], "always_grounded_baseline_pct": 100.0,
           "false_alarms_by_majority": fa, "cases_with_any_ungrounded_run": sorted(
               k for k, r in rows.items() if "U" in r["runs"]), "run_flips": flips, "judge_runs_per_case": Counter(len(r["runs"]) for r in rows.values()),
           "provider_errors": errors}
    out["judge_runs_per_case"] = dict(out["judge_runs_per_case"])
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    json.dump(main(sys.argv[1]), open(ROOT / "eval" / "cap_judge_v3b_report.json", "w"), indent=1)
