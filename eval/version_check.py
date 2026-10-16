#!/usr/bin/env python
"""Week 12 — does retrieval cite the wording that was in force on the LOSS date?

    python eval/version_check.py

Retrieval-level and model-free: no LLM is called, so the number is deterministic and free.
For every boundary case in eval/version_cases.yaml (a loss dated the day before an
endorsement took effect, and one dated on its effective day) it asks the same question twice:

  baseline   today's retrieval as the agent tool calls it — no loss date, no product
  scoped     the same call with loss_date + product, so out-of-force wording is dropped in code

and records, from the top-3 chunks, which VERSION of the clause actually came back.

  right_first       rank 1 is the version in force on the loss date
  wrong_first       rank 1 is the OTHER version — the failure this exercise is about: for a
                    day-before loss that is an endorsement that did not exist yet; for an
                    effective-day loss it is the superseded base clause
  stale_in_top3     the other version appears anywhere in the top 3
  in_force_in_top3  the in-force version appears anywhere in the top 3 (hit@3)

Then, for the bonus, the cost: hit@3 on questions whose gold clause is NOT amended by any
endorsement (eval/questions.yaml `answerable`), baseline vs scoped. A date filter is not free,
and the honest way to know what it cost is to measure it on cases it was never meant to touch.

Markers are validated against the live index before anything is scored: each must appear in
exactly one chunk, and that chunk must belong to the document the case claims.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import store
from src.config import CANDIDATE_K, capstone_chunking
from src.retriever import retrieve

ROOT = Path(__file__).resolve().parent.parent
CORPUS = "insurance"
# Before every endorsement in the corpus (the first takes effect 2026-04-01), and after every
# base wording (all 2025-04-01): the widest filter that still leaves each base clause in force.
NON_STRADDLE_LOSS_DATE = "2026-03-31"
PRODUCT_OF_DOC = {"PW-MOTOR-001": "motor", "PW-HEALTH-002": "health"}


def day_before(iso: str) -> str:
    return (dt.date.fromisoformat(iso) - dt.timedelta(days=1)).isoformat()


def all_chunks() -> list[tuple[str, str, str]]:
    col = store.get_collection(capstone_chunking(), CORPUS)
    res = col.get(include=["documents", "metadatas"])
    return [(i, m.get("document_id"), d)
            for i, m, d in zip(res["ids"], res["metadatas"], res["documents"])]


def validate_markers(topics: list[dict], chunks) -> list[str]:
    problems = []
    for t in topics:
        for side in ("base", "amended"):
            doc, marker = t[side]["doc"], t[side]["marker"]
            found = [cid for cid, _d, txt in chunks if marker in txt]
            if len(found) != 1 or not found[0].startswith(doc + "::"):
                problems.append(f"{t['id']}/{side}: marker {marker!r} matched {found} "
                                f"(expected exactly one chunk of {doc})")
    return problems


def top3(query: str, loss_date: str | None = None, product: str | None = None):
    return retrieve(
        query, cfg=capstone_chunking(), corpus_id=CORPUS, top_k=3, candidate_k=CANDIDATE_K,
        min_cosine=0.0, min_rerank_score=0.0, loss_date=loss_date, product=product,
    ).hits


def score(hits, in_force_marker: str, stale_marker: str) -> dict:
    return {
        "right_first": bool(hits) and in_force_marker in hits[0].text,
        "wrong_first": bool(hits) and stale_marker in hits[0].text,
        "stale_in_top3": any(stale_marker in h.text for h in hits),
        "in_force_in_top3": any(in_force_marker in h.text for h in hits),
        "top3": [h.chunk_id for h in hits],
    }


def run_boundary(topics: list[dict]) -> list[dict]:
    rows = []
    for t in topics:
        for kind, loss in (("day_before", day_before(t["boundary"])),
                           ("effective_day", t["boundary"])):
            in_force, stale = ((t["base"], t["amended"]) if kind == "day_before"
                               else (t["amended"], t["base"]))
            for cond in ("baseline", "scoped"):
                hits = (top3(t["query"]) if cond == "baseline"
                        else top3(t["query"], loss_date=loss, product=t["product"]))
                rows.append({"topic": t["id"], "kind": kind, "loss_date": loss,
                             "condition": cond,
                             **score(hits, in_force["marker"], stale["marker"])})
    return rows


def summarise(rows: list[dict], cond: str, kind: str | None = None) -> dict:
    sel = [r for r in rows if r["condition"] == cond and (kind is None or r["kind"] == kind)]
    n = len(sel)
    return {"n": n,
            **{k: sum(r[k] for r in sel) for k in
               ("right_first", "wrong_first", "stale_in_top3", "in_force_in_top3")}}


def run_non_straddle(questions: list[dict]) -> list[dict]:
    rows = []
    for q in questions:
        if q["kind"] != "answerable":
            continue
        product = PRODUCT_OF_DOC.get(q["expect_doc"])

        def hit(hits):
            return any(h.meta.get("document_id") == q["expect_doc"]
                       and all(x.lower() in h.text.lower() for x in q["expect_text"])
                       for h in hits)

        base = top3(q["question"])
        scoped = top3(q["question"], loss_date=NON_STRADDLE_LOSS_DATE, product=product)
        rows.append({"id": q["id"], "expect_doc": q["expect_doc"], "product": product,
                     "baseline_hit3": hit(base), "scoped_hit3": hit(scoped),
                     "baseline_top1": base[0].chunk_id if base else None,
                     "scoped_top1": scoped[0].chunk_id if scoped else None})
    return rows


def main() -> int:
    topics = yaml.safe_load((ROOT / "eval" / "version_cases.yaml").read_text())["topics"]
    questions = yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text())

    problems = validate_markers(topics, all_chunks())
    if problems:
        print("MARKER VALIDATION FAILED — fix eval/version_cases.yaml before trusting anything:")
        for p in problems:
            print("  -", p)
        return 2
    print(f"markers validated: {2 * len(topics)} markers, each in exactly one chunk of the "
          f"expected document\n")

    rows = run_boundary(topics)
    print(f"BOUNDARY CASES  ({len(topics)} amended clauses x 2 loss dates = "
          f"{len(topics) * 2} cases per condition)")
    print(f"  {'':<22} {'n':>3} {'right-first':>12} {'wrong-first':>12} "
          f"{'stale-in-top3':>14} {'in-force@3':>11}")
    for kind in (None, "day_before", "effective_day"):
        for cond in ("baseline", "scoped"):
            s = summarise(rows, cond, kind)
            label = f"{kind or 'ALL'} / {cond}"
            print(f"  {label:<22} {s['n']:>3} {s['right_first']:>12} {s['wrong_first']:>12} "
                  f"{s['stale_in_top3']:>14} {s['in_force_in_top3']:>11}")

    ns = run_non_straddle(questions)
    n = len(ns)
    b3 = sum(r["baseline_hit3"] for r in ns)
    s3 = sum(r["scoped_hit3"] for r in ns)
    b1 = sum(1 for r in ns if r["baseline_top1"] == r["scoped_top1"])
    print(f"\nNON-STRADDLING QUESTIONS (gold clause not amended by any endorsement), n={n}")
    print(f"  hit@3  baseline {b3}/{n}   scoped {s3}/{n}   "
          f"(scoped loss date {NON_STRADDLE_LOSS_DATE})")
    print(f"  rank-1 chunk unchanged by the filter: {b1}/{n}")
    for r in ns:
        flag = "" if r["baseline_hit3"] == r["scoped_hit3"] else "   <-- changed"
        print(f"    {r['id']:<24} base={r['baseline_hit3']!s:<5} scoped={r['scoped_hit3']!s:<5}{flag}")

    out = ROOT / "eval" / "version_check_results.json"
    out.write_text(json.dumps({"boundary": rows, "non_straddle": ns,
                               "non_straddle_loss_date": NON_STRADDLE_LOSS_DATE},
                              indent=1), encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
