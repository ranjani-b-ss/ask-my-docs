#!/usr/bin/env python
"""Week 12 bonus — loss-date-aware retrieval, proven; and what the filter cost.

    python eval/straddle_bonus.py

Model-free and deterministic (no LLM). Two questions, both answered from the live index:

1. STRADDLE CASES. For each amended clause in eval/version_cases.yaml, the same question is asked with a loss
   dated the DAY BEFORE the endorsement took effect and ON its effective day, under
       baseline = retrieval with no loss date and no product (what the system did before this week)
       scoped   = the same call with loss_date + product, so out-of-force wording is dropped in code
   RED = rank 1 is the version NOT in force on the loss date. GREEN = rank 1 is the version in force.
   The day-before cases are the ones a date filter fixes; the effective-day cases are not (both versions are in
   force that day — the older one is merely superseded), and they are reported separately for exactly that reason.

2. COST. hit@3 on 22 control questions whose answer is in a clause NO endorsement amends (7 from
   eval/questions.yaml + 15 from eval/questions_straddle_control.yaml, authored before any retrieval), asked at
   three loss dates (before every endorsement / between END-2026-01 and END-2026-02 / after all of them) and, for
   documents that apply to every line of business, under both products.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import version_check as vc                                                  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATES = {"before every endorsement": "2026-03-31", "only END-2026-01 in force": "2026-04-15",
         "after every endorsement": "2026-07-01"}
PRODUCTS_FOR = {"motor": ["motor"], "health": ["health"], "all": ["motor", "health"]}


def hit(hits, q) -> bool:
    return any(h.meta.get("document_id") == q["expect_doc"]
               and all(t.lower() in h.text.lower() for t in q["expect_text"]) for h in hits)


def control_questions() -> list[dict]:
    out = []
    for q in yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text()):
        if q["kind"] == "answerable":
            prod = vc.PRODUCT_OF_DOC.get(q["expect_doc"], "all")
            out.append({"id": q["id"], "product": prod, "expect_doc": q["expect_doc"],
                        "question": q["question"], "expect_text": q["expect_text"], "source": "questions.yaml"})
    for q in yaml.safe_load((ROOT / "eval" / "questions_straddle_control.yaml").read_text()):
        out.append({**q, "source": "questions_straddle_control.yaml"})
    return out


def cost(questions: list[dict]) -> dict:
    base = {q["id"]: vc.top3(q["question"]) for q in questions}
    base_hit = {q["id"]: hit(base[q["id"]], q) for q in questions}
    per_date, changes = {}, []
    for label, date in DATES.items():
        trials = lost = gained = same_top1 = n = 0
        scoped_hits = 0
        for q in questions:
            for prod in PRODUCTS_FOR[q["product"]]:
                s = vc.top3(q["question"], loss_date=date, product=prod)
                h = hit(s, q)
                n += 1
                scoped_hits += h
                same_top1 += bool(s and base[q["id"]] and s[0].chunk_id == base[q["id"]][0].chunk_id)
                if base_hit[q["id"]] and not h:
                    lost += 1
                    changes.append({"id": q["id"], "date": date, "product": prod, "change": "LOST hit@3",
                                    "baseline_top3": [x.chunk_id for x in base[q["id"]]],
                                    "scoped_top3": [x.chunk_id for x in s]})
                if h and not base_hit[q["id"]]:
                    gained += 1
                    changes.append({"id": q["id"], "date": date, "product": prod, "change": "GAINED hit@3"})
        per_date[label] = {"loss_date": date, "trials": n, "scoped_hit3": scoped_hits,
                           "baseline_hit3_same_trials": sum(base_hit[q["id"]] for q in questions
                                                            for _ in PRODUCTS_FOR[q["product"]]),
                           "lost": lost, "gained": gained, "rank1_unchanged": same_top1}
    return {"n_questions": len(questions), "baseline_hit3": sum(base_hit.values()),
            "per_date": per_date, "changes": changes,
            "baseline_misses": [i for i, h in base_hit.items() if not h]}


def latency() -> dict:
    """Alternate the two conditions on the same queries and discard a warm-up pass, so neither pays the cold-start."""
    qs = [t["query"] for t in yaml.safe_load((ROOT / "eval" / "version_cases.yaml").read_text())["topics"]]
    for q in qs:                                                    # warm-up, discarded
        vc.top3(q)
        vc.top3(q, loss_date="2026-03-31", product="motor")
    times = {"baseline": [], "scoped": []}
    for _ in range(3):
        for q in qs:
            for cond in ("baseline", "scoped"):
                t0 = time.perf_counter()
                if cond == "baseline":
                    vc.top3(q)
                else:
                    vc.top3(q, loss_date="2026-03-31", product="motor")
                times[cond].append((time.perf_counter() - t0) * 1000)
    return {c: {"p50_ms": round(statistics.median(v)), "n": len(v)} for c, v in times.items()}


def main() -> int:
    topics = yaml.safe_load((ROOT / "eval" / "version_cases.yaml").read_text())["topics"]
    problems = vc.validate_markers(topics, vc.all_chunks())
    if problems:
        print("MARKER VALIDATION FAILED:", *problems, sep="\n  - ")
        return 2
    rows = vc.run_boundary(topics)

    print("STRADDLE CASES — day before the endorsement (the version in force is the OLD one)")
    print("  clean@3 = the in-force clause is in the top 3 AND no out-of-force chunk is. This is the primary measure: the")
    print("  agent reads all three. rank-1 = the first chunk is the in-force version (stricter, reported beside it).")
    print(f"  {'topic':<32}{'baseline':<22}{'scoped':<22}")
    print(f"  {'':<32}{'clean@3  rank-1':<22}{'clean@3  rank-1':<22}")
    red3_b = red3_s = red1_b = red1_s = 0
    for t in topics:
        b = next(r for r in rows if r["topic"] == t["id"] and r["kind"] == "day_before" and r["condition"] == "baseline")
        s = next(r for r in rows if r["topic"] == t["id"] and r["kind"] == "day_before" and r["condition"] == "scoped")
        clean = lambda r: r["in_force_in_top3"] and not r["stale_in_top3"]
        r1 = lambda r: "right" if r["right_first"] else ("WRONG" if r["wrong_first"] else "other")
        red3_b += not clean(b)
        red3_s += not clean(s)
        red1_b += b["wrong_first"]
        red1_s += s["wrong_first"]
        mark = lambda r: ("GREEN" if clean(r) else "RED  ")
        print(f"  {t['id']:<32}{mark(b) + '    ' + r1(b):<22}{mark(s) + '    ' + r1(s):<22}")
    n = len(topics)
    print(f"  not clean@3 (RED):          baseline {red3_b}/{n}   scoped {red3_s}/{n}")
    print(f"  wrong version at rank 1:    baseline {red1_b}/{n}   scoped {red1_s}/{n}")
    print(f"  right version at rank 1:    baseline {sum(r['right_first'] for r in rows if r['kind']=='day_before' and r['condition']=='baseline')}/{n}"
          f"   scoped {sum(r['right_first'] for r in rows if r['kind']=='day_before' and r['condition']=='scoped')}/{n}")
    red_before, red_after = red3_b, red3_s

    print("\nEFFECTIVE-DAY cases (both versions in force; the older is superseded) — the date filter cannot help")
    eff_b = sum(r["wrong_first"] for r in rows if r["kind"] == "effective_day" and r["condition"] == "baseline")
    eff_s = sum(r["wrong_first"] for r in rows if r["kind"] == "effective_day" and r["condition"] == "scoped")
    print(f"  RED at rank 1:  baseline {eff_b}/{len(topics)}   scoped {eff_s}/{len(topics)}")
    for r in rows:
        if r["kind"] == "effective_day" and r["condition"] == "scoped" and r["wrong_first"]:
            print(f"    still red: {r['topic']}  top3={r['top3']}")

    cq = control_questions()
    c = cost(cq)
    print(f"\nCOST — {c['n_questions']} control questions (answer not in any amended clause); baseline hit@3 "
          f"{c['baseline_hit3']}/{c['n_questions']}  (misses: {c['baseline_misses']})")
    for label, d in c["per_date"].items():
        print(f"  scoped at {d['loss_date']} ({label}): hit@3 {d['scoped_hit3']}/{d['trials']} trials "
              f"(baseline same trials {d['baseline_hit3_same_trials']})  lost {d['lost']}  gained {d['gained']}  "
              f"rank-1 unchanged {d['rank1_unchanged']}/{d['trials']}")
    for ch in c["changes"]:
        print(f"    {ch['change']}: {ch['id']} @ {ch['date']} {ch['product']}")
    lat = latency()
    print(f"\nLATENCY (p50 of {lat['baseline']['n']} calls): baseline {lat['baseline']['p50_ms']} ms, "
          f"scoped {lat['scoped']['p50_ms']} ms")

    (ROOT / "eval" / "straddle_bonus_results.json").write_text(
        json.dumps({"boundary": rows, "red_day_before_not_clean_at_3": {"baseline": red3_b, "scoped": red3_s, "n": len(topics)},
                    "wrong_at_rank1_day_before": {"baseline": red1_b, "scoped": red1_s, "n": len(topics)},
                    "red_effective_day": {"baseline": eff_b, "scoped": eff_s, "n": len(topics)},
                    "control_cost": c, "latency": lat}, indent=1), encoding="utf-8")
    print("\nwrote eval/straddle_bonus_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
