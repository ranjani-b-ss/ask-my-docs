#!/usr/bin/env python
"""Bonus — RAGAS-style faithfulness and context precision over the claim summaries.

    python eval/ragas_metrics.py
    python eval/ragas_metrics.py --limit 5

Two metrics that answer two different questions, and the gap between them is the point:

  FAITHFULNESS      of the claims the summary makes, what fraction can be inferred from the
                    retrieved passages? Measures whether the model invented anything.
                    Computed the RAGAS way: decompose the summary into atomic claims, then
                    verify each one against the context. supported / total.

  CONTEXT PRECISION of the passages that were retrieved, what fraction actually bear on the
                    coverage question? Measures whether retrieval did its job. Computed as
                    mean precision@k over the ranked list, so a relevant passage at rank 1
                    counts for more than the same passage at rank 5.

A summary can score 1.00 faithfulness and still be dangerously wrong, because faithfulness
only asks "did you make this up", never "was the material you were given the right
material". When retrieval hands the model the wrong clause, a perfectly faithful summary of
the wrong clause is the output — confidently, faithfully wrong. Faithfulness cannot see it.
Context precision can.

Which is why the two numbers are reported per case and never averaged together.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import llm
from src.generator import format_context
from run_evalset import rehydrate

ROOT = Path(__file__).resolve().parent.parent

CLAIMS_PROMPT = """\
Break the SUMMARY into its atomic factual claims — each a single assertion about coverage, a \
figure, a limit, a deadline, or an exclusion. Ignore the claim number, the date of loss and \
the line of business; they are copied from the claim file, not inferred from the passages.

Then, for EACH claim, decide whether it can be inferred from the numbered POLICY PASSAGES \
alone. Restating the claim file's own facts counts as inferable.

POLICY PASSAGES
{context}

SUMMARY
{summary}

Reply with one line per claim, in this exact format and nothing else:
YES | <the claim in under 15 words>
NO  | <the claim in under 15 words>
"""

PRECISION_PROMPT = """\
A claims adjuster asked this coverage question about an insurance claim:

QUESTION: {question}

Below are the {n} policy passages that were retrieved to answer it, in rank order. For each, \
say whether it is USEFUL for answering that specific question — that is, whether an adjuster \
would need to read it to decide the point. A passage on the right general topic but about a \
different provision is NOT useful.

{passages}

Reply with exactly {n} lines, nothing else:
1: USEFUL or NOT
2: USEFUL or NOT
(and so on, one per passage, in the same order)
"""

_CLAIM_LINE = re.compile(r"^\s*(YES|NO)\s*\|\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_PREC_LINE = re.compile(r"^\s*(\d+)\s*:\s*(USEFUL|NOT)", re.IGNORECASE | re.MULTILINE)


def faithfulness(summary, provider=None, model=None) -> tuple[float | None, list]:
    """RAGAS faithfulness: fraction of the summary's atomic claims inferable from context."""
    body = "\n".join(
        line for line in summary.text.splitlines()
        if not line.lower().startswith(("claim number", "date of loss", "line:"))
    )
    try:
        raw = llm.chat("You verify claims against source passages. You are strict and you "
                       "answer in the exact format requested.",
                       CLAIMS_PROMPT.format(context=format_context(summary.hits),
                                            summary=body),
                       provider=provider, model=model)
    except Exception as exc:
        return None, [f"error: {exc}"]

    claims = [(m.group(1).upper(), m.group(2).strip()) for m in _CLAIM_LINE.finditer(raw)]
    if not claims:
        return None, ["no claims parsed"]
    supported = sum(1 for verdict, _ in claims if verdict == "YES")
    return supported / len(claims), claims


def context_precision(summary, question: str, provider=None, model=None) -> tuple[float | None, list]:
    """Mean precision@k over the ranked passages, relevance judged per passage.

    Rank-weighted on purpose: retrieval that puts the one useful passage last has done a
    worse job than retrieval that puts it first, even though both "retrieved it".
    """
    if not summary.hits:
        return None, []
    blocks = []
    for i, hit in enumerate(summary.hits, start=1):
        section = hit.meta.get("section") or "(no section)"
        blocks.append(f"[{i}] {hit.meta.get('document_id')} > {section}\n{hit.text[:700]}")
    try:
        raw = llm.chat("You assess whether a passage is useful for a specific question. You "
                       "answer in the exact format requested.",
                       PRECISION_PROMPT.format(question=question, n=len(summary.hits),
                                               passages="\n\n---\n\n".join(blocks)),
                       provider=provider, model=model)
    except Exception as exc:
        return None, [f"error: {exc}"]

    verdicts = {int(m.group(1)): m.group(2).upper() == "USEFUL"
                for m in _PREC_LINE.finditer(raw)}
    flags = [verdicts.get(i, False) for i in range(1, len(summary.hits) + 1)]
    if not any(flags):
        return 0.0, flags
    running, precisions = 0, []
    for k, relevant in enumerate(flags, start=1):
        if relevant:
            running += 1
            precisions.append(running / k)
    return sum(precisions) / len(precisions), flags


def coverage_question(notes: str) -> str:
    for line in notes.splitlines():
        if line.strip().lower().startswith("coverage question"):
            return line.split(":", 1)[1].strip()
    return notes.strip()[:200]


def main() -> int:
    ap = argparse.ArgumentParser(description="RAGAS faithfulness + context precision")
    ap.add_argument("--summaries", default="eval/summaries.json")
    ap.add_argument("--cases", default="eval/claim_cases.yaml")
    ap.add_argument("--out", default="eval/ragas.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.2)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    rows = json.loads((ROOT / args.summaries).read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in
             yaml.safe_load((ROOT / args.cases).read_text(encoding="utf-8"))["cases"]}
    if args.limit:
        rows = rows[: args.limit]

    print(f"  {'case':<30} {'mode':<26} {'faith':>6} {'ctxP':>6}  relevant passages")
    print(f"  {'-'*30} {'-'*26} {'-'*6} {'-'*6}  {'-'*20}")
    results = []
    for i, row in enumerate(rows, start=1):
        summary = rehydrate(row)
        case = cases[row["case_id"]]
        question = coverage_question(case["notes"])

        f, claims = faithfulness(summary, args.provider, args.model)
        time.sleep(args.sleep)
        p, flags = context_precision(summary, question, args.provider, args.model)

        results.append({
            "case_id": row["case_id"], "mode": row["mode"], "corpus": row["corpus"],
            "faithfulness": f, "context_precision": p,
            "n_claims": len(claims) if claims else 0,
            "claims": [{"supported": v == "YES", "claim": c} for v, c in (claims or [])
                       if isinstance(c, str)],
            "passage_relevance": flags,
        })
        marks = "".join("R" if x else "." for x in flags) if flags else "-"
        print(f"  {row['case_id']:<30} {row['mode']:<26} "
              f"{(f'{f:.2f}' if f is not None else '  -'):>6} "
              f"{(f'{p:.2f}' if p is not None else '  -'):>6}  {marks}")
        if args.sleep and i < len(rows):
            time.sleep(args.sleep)

    fs = [r["faithfulness"] for r in results if r["faithfulness"] is not None]
    ps = [r["context_precision"] for r in results if r["context_precision"] is not None]
    print(f"\n  mean faithfulness      {sum(fs)/len(fs):.3f}   over {len(fs)} cases")
    print(f"  mean context precision {sum(ps)/len(ps):.3f}   over {len(ps)} cases")

    # The cases the averages hide: faithful to the passages, but the passages were wrong.
    # `(x or 1) <= 0.5` was the first version of this filter and it silently dropped every
    # context precision of exactly 0.00 — `0.0 or 1` is 1 in Python. The cases it hid were
    # the four worst in the run, including the one where retrieval returned nothing useful at
    # all. A falsy-zero bug in the tool built to stop averages hiding things.
    danger = sorted(
        (r for r in results
         if r["faithfulness"] is not None and r["faithfulness"] >= 0.9
         and r["context_precision"] is not None and r["context_precision"] <= 0.5),
        key=lambda r: r["context_precision"],
    )
    print(f"\n  CONFIDENTLY, FAITHFULLY WRONG — faithfulness >= 0.90 AND context "
          f"precision <= 0.50")
    if danger:
        for r in danger:
            print(f"    {r['case_id']:<30} faithfulness {r['faithfulness']:.2f}   "
                  f"context precision {r['context_precision']:.2f}   [{r['mode']}]")
    else:
        print("    none in this run")

    Path(args.out).write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print(f"\n  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
