#!/usr/bin/env python
"""Generate the claim summaries, so they can be hand-labelled before any judge exists.

    python eval/make_summaries.py                 # all cases -> eval/summaries.json
    python eval/make_summaries.py --limit 3       # smoke test

Deliberately a separate step from both the judge and the eval. The blind protocol needs the
summaries to exist as a frozen artefact that a human reads and labels, with the judge not yet
having run against them. If the eval generated summaries and judged them in one pass there
would be no point in the run where labelling is possible, and the validation would be
impossible rather than merely unconvincing.

The output is committed. It is the thing the labels refer to, so a label file without the
summaries it describes cannot be checked by anyone.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DEFAULT_CHUNKING
from src.summariser import summarise
from src import store

OUT = Path(__file__).resolve().parent / "summaries.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Write claim summaries for the eval set")
    ap.add_argument("--cases", default="eval/claim_cases.yaml")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    cases = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.limit:
        cases = cases[: args.limit]

    for corpus in sorted({c["corpus"] for c in cases}):
        if not store.collection_exists(DEFAULT_CHUNKING, corpus):
            print(f"No index for '{corpus}'. Run: python cli.py --corpus {corpus} ingest",
                  file=sys.stderr)
            return 1

    rows = []
    for i, case in enumerate(cases, start=1):
        summary = summarise(case["id"], case["notes"], corpus_id=case["corpus"],
                            provider=args.provider, model=args.model)
        position = summary.get("position") or "-"
        print(f"  {i:>3}/{len(cases)}  {case['id']:<30} {case['mode']:<26} "
              f"{position[:14]:<14} {'ok' if summary.text else summary.reason[:30]}")
        rows.append({
            "case_id": case["id"],
            "mode": case["mode"],
            "corpus": case["corpus"],
            "regression_of": case.get("regression_of"),
            "notes": case["notes"],
            "query": summary.query,
            "summary": summary.text,
            "fields": summary.fields,
            "retrieved": [
                {"rank": r, "chunk_id": h.chunk_id,
                 "document_id": h.meta.get("document_id"),
                 "section": h.meta.get("section") or None,
                 "page": h.meta.get("page"),
                 "effective_date": h.meta.get("effective_date") or None,
                 "cosine": h.cosine, "rerank": h.rerank_score}
                for r, h in enumerate(summary.hits, start=1)
            ],
            "mode_of_generation": summary.mode,
            "reason": summary.reason,
            "prompt_version": summary.diagnostics.get("prompt_version"),
            "model": summary.diagnostics.get("model"),
            "params": summary.diagnostics.get("params"),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        if args.sleep and i < len(cases):
            time.sleep(args.sleep)

    Path(args.out).write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    ok = sum(1 for r in rows if r["summary"])
    print(f"\n{ok}/{len(rows)} summaries written -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
