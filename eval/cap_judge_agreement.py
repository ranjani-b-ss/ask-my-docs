"""Week 12 — judge agreement with the hand labels (natural set) and recall on the planted set.

    python eval/cap_judge_agreement.py eval/cap_judge_v1_dev.json [--split dev]

Reports, for the natural set: agreement, the always-GROUNDED baseline, Cohen's kappa, the confusion matrix and
a Wilson interval — and, because UNGROUNDED is rare, says plainly when agreement is uninformative. For the planted
set: recall of UNGROUNDED by error type and the false-positive rate on the controls. Run-to-run flips if >1 run.
"""

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def kappa(pairs):
    n = len(pairs)
    if n == 0:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ca[x] / n) * (cb[x] / n) for x in set(ca) | set(cb))
    return None if pe == 1 else (po - pe) / (1 - pe)


def majority(runs):
    v = [r["verdict"] for r in runs if r["verdict"] != "ERROR"]
    if not v:
        return "ERROR"
    c = Counter(v).most_common()
    return c[0][0] if len(c) == 1 or c[0][1] > c[1][1] else "UNGROUNDED"      # a tie is a flag, not a pass


def report(path: Path, split: str | None) -> dict:
    res = json.loads(path.read_text())
    meta = res.pop("_meta", {})
    labels = json.loads((ROOT / "eval" / "labels_cap_70.json").read_text())["labels"]
    planted = {p["id"]: p for p in json.loads((ROOT / "eval" / "planted_cap.json").read_text())}
    nat, pl = [], []
    errors = 0
    flips = 0
    multi = 0
    for rid, r in res.items():
        if split and r["split"] != split:
            continue
        errors += sum(x["verdict"] == "ERROR" for x in r["runs"])
        verdicts = {x["verdict"] for x in r["runs"] if x["verdict"] != "ERROR"}
        if len(r["runs"]) > 1:
            multi += 1
            flips += len(verdicts) > 1
        v = majority(r["runs"])
        if v == "ERROR":
            continue
        if r["kind"] == "natural":
            nat.append((rid, labels[r["key"]]["label"], v))
        else:
            pl.append((r["key"], planted[r["key"]]["label"], planted[r["key"]]["type"], v))
    out = {"meta": meta, "split": split or "all"}
    n = len(nat)
    agree = sum(h == j for _, h, j in nat)
    base_label = Counter(h for _, h, _ in nat).most_common(1)[0][0] if nat else None
    base = sum(h == base_label for _, h, _ in nat) / n if n else 0
    tp = sum(h == "UNGROUNDED" and j == "UNGROUNDED" for _, h, j in nat)
    fn = sum(h == "UNGROUNDED" and j == "GROUNDED" for _, h, j in nat)
    fp = sum(h == "GROUNDED" and j == "UNGROUNDED" for _, h, j in nat)
    tn = sum(h == "GROUNDED" and j == "GROUNDED" for _, h, j in nat)
    out["natural"] = {"n": n, "agreement": agree / n if n else None, "agreed": agree,
                      "wilson95": [round(x, 3) for x in wilson(agree, n)],
                      "always_majority_baseline": round(base, 3), "baseline_label": base_label,
                      "kappa": None if kappa([(h, j) for _, h, j in nat]) is None else round(kappa([(h, j) for _, h, j in nat]), 3),
                      "confusion": {"both_grounded": tn, "both_ungrounded": tp,
                                    "judge_grounded_human_ungrounded(missed)": fn,
                                    "judge_ungrounded_human_grounded(false alarm)": fp},
                      "disagreements": [{"case": c, "human": h, "judge": j} for c, h, j in nat if h != j],
                      "human_ungrounded_n": tp + fn}
    ung = [x for x in pl if x[1] == "UNGROUNDED"]
    ctl = [x for x in pl if x[1] == "GROUNDED"]
    bytype = defaultdict(lambda: [0, 0])
    for _, _, t, j in ung:
        bytype[t][1] += 1
        bytype[t][0] += j == "UNGROUNDED"
    out["planted"] = {"recall": f"{sum(j == 'UNGROUNDED' for *_, j in ung)}/{len(ung)}",
                      "recall_wilson95": [round(x, 3) for x in wilson(sum(j == 'UNGROUNDED' for *_, j in ung), len(ung))],
                      "by_type": {t: f"{a}/{b}" for t, (a, b) in bytype.items()},
                      "controls_flagged": f"{sum(j == 'UNGROUNDED' for *_, j in ctl)}/{len(ctl)}",
                      "missed": [pid for pid, _, _, j in ung if j == "GROUNDED"],
                      "controls_flagged_ids": [pid for pid, _, _, j in ctl if j == "UNGROUNDED"]}
    out["provider_errors"] = errors
    out["cases_with_repeat_runs"] = multi
    out["cases_whose_verdict_flipped_between_runs"] = flips
    return out


if __name__ == "__main__":
    split = sys.argv[sys.argv.index("--split") + 1] if "--split" in sys.argv else None
    print(json.dumps(report(Path(sys.argv[1]), split), indent=1))
