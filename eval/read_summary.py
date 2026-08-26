#!/usr/bin/env python
"""Print a claim summary beside the passages it was written from, for hand-labelling.

    python eval/read_summary.py --ids cb-tyres-only,m1-consumables --chars 700
    python eval/read_summary.py --all --chars 500

This is the instrument for the blind labelling pass. It shows the claim file, every retrieved
passage with its text, and the summary — and deliberately shows NO judge output, because the
labels have to be written without it. There is no flag to display a verdict; the file it would
come from does not exist yet when this is used.

Read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DEFAULT_CHUNKING
from src import store

SUMMARIES = Path(__file__).resolve().parent / "summaries.json"


def wrap(text: str, indent: str = "      ", width: int = 96) -> str:
    out = []
    for para in (text or "").strip().split("\n"):
        out.extend(textwrap.wrap(para, width=width, initial_indent=indent,
                                 subsequent_indent=indent) or [indent])
    return "\n".join(out)


def show(row: dict, n: int, chars: int) -> None:
    print("\n" + "=" * 104)
    print(f"### {n}. {row['case_id']}   mode={row['mode']}   corpus={row['corpus']}"
          + (f"   REGRESSION of {row['regression_of']}" if row.get("regression_of") else ""))
    print("=" * 104)
    print("CLAIM FILE")
    print(wrap(row["notes"]))
    print(f"\nRETRIEVAL QUERY: {row['query']}")

    collection = store.get_collection(DEFAULT_CHUNKING, row["corpus"])
    fetched = store.get_by_ids(collection, [h["chunk_id"] for h in row["retrieved"]])

    print(f"\nPASSAGES SUPPLIED TO THE MODEL ({len(row['retrieved'])})")
    for h in row["retrieved"]:
        got = fetched.get(h["chunk_id"])
        print(f"\n  [{h['rank']}] {h['document_id']}  ({h['chunk_id']})")
        print(f"      eff={h['effective_date'] or '-'}  page={h['page'] or '-'}  "
              f"cos={h['cosine']}  rerank={h['rerank']}")
        print(f"      section: {h['section'] or '(none)'}")
        print(wrap(got["text"][:chars]) if got else "      (chunk missing from index)")

    print("\nSUMMARY PRODUCED")
    print(wrap(row["summary"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Read summaries with their source passages")
    ap.add_argument("--summaries", default=str(SUMMARIES))
    ap.add_argument("--ids", default="", help="comma-separated case ids")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--chars", type=int, default=600)
    args = ap.parse_args()

    rows = json.loads(Path(args.summaries).read_text(encoding="utf-8"))
    if args.ids:
        wanted = [i.strip() for i in args.ids.split(",") if i.strip()]
        by_id = {r["case_id"]: r for r in rows}
        missing = [i for i in wanted if i not in by_id]
        if missing:
            raise SystemExit(f"unknown case id(s): {missing}")
        rows = [by_id[i] for i in wanted]
    elif not args.all:
        raise SystemExit("pass --ids or --all")

    for i, row in enumerate(rows, start=1):
        show(row, i, args.chars)
    return 0


if __name__ == "__main__":
    sys.exit(main())
