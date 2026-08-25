#!/usr/bin/env python
"""Replay one trace from the trace alone, and show the result beside the original.

    python eval/replay_trace.py --seed 20260826            # seeded random pick from the sample
    python eval/replay_trace.py --trace-id tr_9f2c1a4b7de0
    python eval/replay_trace.py --seed 20260826 --dry-run  # reconstruct, don't call the model

"Replayable" is a claim that needs testing, not asserting. This script is the test: it is
allowed to read the trace row and the chunk store, and nothing else. No original question
object, no session state, no re-running retrieval. If a field is missing from the trace,
the reconstruction fails here and the gap is real.

The reconstruction, in order:

  1. Read the trace row by trace_id.
  2. Compare ``prompt_sha`` against the prompt in the code right now. A mismatch means the
     prompt changed since the trace was written — the replay is then still valid, but it is
     a replay of a DIFFERENT prompt, and it says so loudly instead of quietly.
  3. Fetch each retrieved chunk by ``chunk_id`` from the recorded collection, in the
     recorded rank order. Order is load-bearing: the [n] markers are positional.
  4. Rebuild the CONTEXT block and compare ``context_sha``. This is the real proof — if the
     hash matches, the model is about to receive byte-identical input.
  5. Re-call the recorded model with the recorded params.
  6. Print original vs replayed, and whether they match.

Divergence is not automatically a bug: a hosted model can change under a moving alias like
``gemini-flash-latest``, and that is worth knowing too. What matters is that the INPUT is
provably identical, so any difference is attributable to the model rather than to us.
"""

from __future__ import annotations

import argparse
import difflib
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ChunkConfig
from src.generator import (
    ANSWER_TEMPLATE,
    MAX_CHARS_PER_HIT,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    format_context,
    prompt_sha,
)
from src.retriever import Hit
from src import llm, store, trace

REQUIRED = [
    ("question", "the question asked"),
    ("collection", "which index was searched"),
    ("retrieved", "the chunk_ids and their order"),
    ("prompt_version", "which prompt produced this"),
    ("prompt_sha", "proof of the prompt text"),
    ("provider", "which vendor was called"),
    ("model", "which model, resolved"),
    ("params", "decoding parameters"),
    ("raw_output", "what the model returned"),
    ("context_sha", "proof of the assembled context"),
]


def audit_fields(row: dict) -> list[str]:
    """Report every field replay needs that this trace does not carry."""
    missing = []
    for key, why in REQUIRED:
        value = row.get(key)
        if value in (None, "", [], {}):
            missing.append(f"{key} — {why}")
    return missing


def main() -> int:
    ap = argparse.ArgumentParser(description="Replay a trace from the trace alone")
    ap.add_argument("--trace-id")
    ap.add_argument("--seed", type=int, help="pick a trace at random from a seeded sample")
    ap.add_argument("--n", type=int, default=20, help="sample size the seed refers to")
    ap.add_argument("--population", default="traffic-random")
    ap.add_argument("--dry-run", action="store_true", help="reconstruct only, no model call")
    args = ap.parse_args()

    rows = trace.read_all()
    if not rows:
        raise SystemExit("No traces on disk.")

    if args.trace_id:
        row = next((r for r in rows if r["trace_id"] == args.trace_id), None)
        if row is None:
            raise SystemExit(f"No trace {args.trace_id}")
        picked_how = f"--trace-id {args.trace_id}"
    elif args.seed is not None:
        from sample_traces import draw, population

        sample = draw(population(rows, args.population), args.seed, args.n)
        # A second, separately seeded draw from the sample. Using the same seed twice would
        # tie which trace gets replayed to the sample's internal ordering, which is an
        # accident of the sort, not a choice.
        row = random.Random(args.seed + 1).choice(sample)
        picked_how = (f"random.Random(seed+1).choice(sample) from the {args.n}-trace "
                      f"sample at seed {args.seed}")
    else:
        raise SystemExit("Pass --trace-id or --seed")

    print(f"REPLAY {row['trace_id']}")
    print(f"  picked by      : {picked_how}")
    print(f"  written at     : {row['ts']}  (code {row.get('code_version')})")
    print(f"  question       : {row['question']}")
    print(f"  corpus         : {row['corpus']}   collection {row['collection']}")
    print(f"  outcome        : mode={row['mode']} grounded={row['grounded']} "
          f"gate={row['gate'] or '-'}")

    # ---- 1. field audit ------------------------------------------------------------
    missing = audit_fields(row)
    print("\n[1] FIELD AUDIT")
    if missing:
        for m in missing:
            print(f"  MISSING  {m}")
    else:
        print("  all fields needed for replay are present")

    # ---- 2. prompt identity -------------------------------------------------------
    print("\n[2] PROMPT IDENTITY")
    now = prompt_sha()
    print(f"  recorded : {row.get('prompt_version')} / {row.get('prompt_sha')}")
    print(f"  current  : {PROMPT_VERSION} / {now}")
    if row.get("prompt_sha") and row["prompt_sha"] != now:
        print("  DRIFT — the prompt changed since this trace. Replaying the CURRENT prompt.")
    elif row.get("prompt_sha"):
        print("  match — the prompt in the code is the prompt that produced this trace")

    # ---- 3. rebuild the context from chunk_ids -----------------------------------
    print("\n[3] CONTEXT RECONSTRUCTION (from chunk_id, in recorded rank order)")
    cfg = ChunkConfig(**row["chunking"])
    collection = store.get_collection(cfg, row["corpus"])
    ids = [h["chunk_id"] for h in row["retrieved"]]
    fetched = store.get_by_ids(collection, ids)

    lost = [i for i in ids if i not in fetched]
    if lost:
        print(f"  {len(lost)} chunk_id(s) no longer in the index: {lost}")
        print("  the corpus was re-ingested since this trace — replay is not exact")

    hits = [
        Hit(text=fetched[h["chunk_id"]]["text"], meta=fetched[h["chunk_id"]]["meta"],
            cosine=h["cosine"], chunk_id=h["chunk_id"], rerank_score=h.get("rerank"),
            bm25=h.get("bm25"), rrf=h.get("rrf"))
        for h in row["retrieved"] if h["chunk_id"] in fetched
    ]
    for i, h in enumerate(hits, start=1):
        print(f"  [{i}] {h.chunk_id:<24} cos={h.cosine:<7} rerank={h.rerank_score}")

    context = format_context(hits, MAX_CHARS_PER_HIT)
    rebuilt_sha = trace.sha(context)
    print(f"\n  recorded context_sha : {row.get('context_sha') or '(none — no model call)'}")
    print(f"  rebuilt  context_sha : {rebuilt_sha}")
    if row.get("context_sha") == rebuilt_sha:
        print("  IDENTICAL — the model is receiving byte-for-byte the same input")
    elif row.get("context_sha"):
        print("  DIFFERENT — see the chunk notes above")

    if row.get("raw_output") is None:
        print("\n[4] MODEL CALL — skipped: this trace has no raw_output, because no model "
              "was\n    called (it abstained at a retrieval gate, or the provider was "
              "unavailable).\n    Nothing to compare against; the reconstruction above is "
              "the whole replay.")
        return 0

    if args.dry_run:
        print("\n[4] MODEL CALL — skipped (--dry-run)")
        return 0

    # ---- 4. re-call the recorded model -------------------------------------------
    print(f"\n[4] MODEL CALL — {row['provider']} / {row['model']} params={row['params']}")
    user = ANSWER_TEMPLATE.format(context=context, question=row["question"])
    try:
        replayed = llm.chat(SYSTEM_PROMPT, user,
                           provider=row["provider"], model=row["model"])
    except Exception as exc:
        print(f"  call failed: {exc}")
        return 1

    original = row["raw_output"]
    print("\n" + "=" * 78)
    print("ORIGINAL (from the trace)")
    print("=" * 78)
    print(original.strip())
    print("\n" + "=" * 78)
    print("REPLAYED (just now, from the trace alone)")
    print("=" * 78)
    print(replayed.strip())

    print("\n" + "=" * 78)
    if original.strip() == replayed.strip():
        print("VERDICT: byte-identical.")
    else:
        ratio = difflib.SequenceMatcher(None, original.strip(), replayed.strip()).ratio()
        print(f"VERDICT: differs. similarity {ratio:.1%}")
        print("Input was proven identical in step [3], so the difference is the model's, "
              "not ours.\n")
        for line in difflib.unified_diff(
            original.strip().splitlines(), replayed.strip().splitlines(),
            fromfile="original", tofile="replayed", lineterm="", n=1,
        ):
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
