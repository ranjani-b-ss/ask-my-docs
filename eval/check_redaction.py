#!/usr/bin/env python
"""Prove claimant identifiers are redacted BEFORE the trace is written, not after.

    python eval/check_redaction.py

Two separate claims need evidence, and they are not the same claim:

  A. ORDER — redaction happens on the way in. Checked structurally, by feeding a trace
     containing identifiers through the real writer with the trace file redirected to a
     temporary path, then reading that file back. If the raw identifier ever touched disk
     it would be in there. A cleanup pass that ran afterwards would fail this test, because
     the writer is the only thing running.

  B. COVERAGE — no identifier survives anywhere in the real trace file. Checked by scanning
     every line of traces/traces.jsonl with the same patterns.

A passes or fails on code order. B passes or fails on pattern quality. Reporting only B
would let a "we scrub it later" implementation look clean.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import redact, trace
from src.config import TRACE_FILE

PROBE = (
    "Claimant Mr. Rajesh Kumar, claim no. CLM-2026-004871, mobile 98765 43210, "
    "email rajesh.kumar@example.com, Aadhaar 1234 5678 9012, PAN ABCDE1234F. "
    "Policy POL/TN/88213. The deductible is Rs. 10,000 under Section C) 2 and the "
    "sum insured is 500000."
)

MUST_SURVIVE = ["Rs. 10,000", "Section C) 2", "500000", "deductible"]


def main() -> int:
    failures = 0

    # ---- A. order of operations --------------------------------------------------
    print("A. ORDER — is redaction applied before the write?\n")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "probe.jsonl"
        original = trace.TRACE_FILE
        trace.TRACE_FILE = target          # redirect the real writer
        try:
            trace.record(question=PROBE, answer=PROBE, raw_output=PROBE,
                         corpus="probe", surface="redaction-selftest",
                         gate_detail=PROBE)
        finally:
            trace.TRACE_FILE = original

        written = target.read_text(encoding="utf-8")
        row = json.loads(written)

    print(f"   probe in  : {PROBE[:78]}…")
    print(f"   on disk   : {row['question'][:78]}…\n")

    for field in ("question", "answer", "raw_output", "gate_detail"):
        leaked = redact.contains_identifier(row[field])
        print(f"   {'FAIL' if leaked else 'ok  '}  {field}: "
              f"{'identifier reached disk' if leaked else 'redacted on the way in'}")
        failures += leaked

    kept = [s for s in MUST_SURVIVE if s in row["question"]]
    print(f"\n   policy figures preserved: {len(kept)}/{len(MUST_SURVIVE)}  {kept}")
    if len(kept) != len(MUST_SURVIVE):
        print("   FAIL — over-redaction; the trace would be unreadable for error analysis")
        failures += 1

    # ---- B. coverage over the live trace file ------------------------------------
    print(f"\nB. COVERAGE — scan every line of {TRACE_FILE.name}\n")
    rows = trace.read_all()
    if not rows:
        print("   no traces on disk yet — nothing to scan")
        return 1 if failures else 0

    hits = []
    for r in rows:
        blob = json.dumps(r, ensure_ascii=False)
        if redact.contains_identifier(blob):
            hits.append(r["trace_id"])

    n_marked = sum(1 for r in rows if redact.REDACTED in json.dumps(r, ensure_ascii=False))
    print(f"   traces scanned            : {len(rows)}")
    print(f"   traces containing {redact.REDACTED} : {n_marked}")
    print(f"   traces with a surviving identifier: {len(hits)}")
    if hits:
        print(f"   FAIL — {hits[:10]}")
        failures += 1
    else:
        print("   ok — no claimant name, claim number, phone, email, Aadhaar, PAN or "
              "policy number\n        survives anywhere in the trace file")

    print(f"\n{'FAILED' if failures else 'PASSED'} — {failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
