"""Append-only log of agent runs, one JSON line per completed (or budget-stopped) task.

Same discipline as ``src/trace.py`` from Week 5, and a separate file rather than reusing that
one: these lines are shaped completely differently (a list of ReAct laps, not a single
retrieval), and mixing the two schemas in one file would make both harder to read.

That said, one piece of Week 5's discipline was missing here until now: every claim's adjuster
notes flow through ``get_claim`` into every lap's transcript and observation text, which is
exactly the free-text, PII-dense field Week 5's redaction was built for — and this writer was
appending it unscrubbed. Redact, then append, in that order, same as ``src/trace.py``'s own
``_write``. ``redact.scrub_deep`` only touches strings and recurses through dicts/lists, so the
claim_id, statuses, amounts and every other structural field a claim's own record depends on
pass through unchanged — see ``eval/check_redaction.py`` for the test that this doesn't mangle
policy figures or claim ids.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .. import redact
from ..config import PROJECT_ROOT

TRACE_FILE = PROJECT_ROOT / "traces" / "agent_traces.jsonl"


def record(result: dict) -> None:
    row = redact.scrub_deep({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **result})
    TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read_all() -> list[dict]:
    if not TRACE_FILE.exists():
        return []
    return [json.loads(line) for line in TRACE_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()]
