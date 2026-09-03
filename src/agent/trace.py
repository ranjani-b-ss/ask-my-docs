"""Append-only log of agent runs, one JSON line per completed (or budget-stopped) task.

Same discipline as ``src/trace.py`` from Week 5, and a separate file rather than reusing that
one: these lines are shaped completely differently (a list of ReAct laps, not a single
retrieval), and mixing the two schemas in one file would make both harder to read.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..config import PROJECT_ROOT

TRACE_FILE = PROJECT_ROOT / "traces" / "agent_traces.jsonl"


def record(result: dict) -> None:
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **result}
    TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read_all() -> list[dict]:
    if not TRACE_FILE.exists():
        return []
    return [json.loads(line) for line in TRACE_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()]
