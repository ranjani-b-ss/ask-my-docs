"""Week 5 — the trace log.

One JSON object per request, appended to ``traces/traces.jsonl``. A trace is only worth
having if it is *replayable*: you must be able to reconstruct the exact model call from the
trace alone, months later, without the original session. That sets a hard requirement list,
and every field below exists because leaving it out breaks replay:

    prompt_version + prompt_sha    which prompt text produced this. A version string alone
                                   is a promise; the hash is proof, and catches an edit
                                   someone forgot to bump.
    retrieved[].chunk_id + scores  the exact passages, in the exact order. Order matters:
                                   the [n] citation markers are positional, so a trace that
                                   records the set but not the order cannot be replayed.
    model + params                 temperature, max tokens, provider. "gemini" is not
                                   enough — gemini-flash-latest is an alias that moves.
    raw_output                     what the model actually returned, before any gate or
                                   formatting touched it. The post-processed answer is the
                                   app's opinion; the raw string is the evidence.
    gates                          which gate fired, with the number it fired on. Without
                                   this, an abstention and a model refusal look identical.

Everything written here passes through :mod:`src.redact` first — see ``_write``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import redact
from .config import TRACE_FILE, TRACE_SCHEMA_VERSION

_git_sha: str | None = None


def code_version() -> str:
    """Git SHA of the running code, so a trace can be tied to the app that produced it."""
    global _git_sha
    if _git_sha is None:
        root = Path(__file__).resolve().parent.parent
        try:
            sha_out = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=root, capture_output=True, text=True, timeout=5,
            ).stdout.strip() or "unknown"
            # A bare SHA on a dirty tree is a lie: it points at a commit that does not
            # contain the code that produced the trace. Replay would then be compared
            # against the wrong source.
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root, capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            _git_sha = f"{sha_out}-dirty" if dirty else sha_out
        except Exception:
            _git_sha = "unknown"
    return _git_sha


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def new_trace_id() -> str:
    """Random, not sequential. Sequential ids leak volume and invite off-by-one sampling."""
    return f"tr_{uuid.uuid4().hex[:12]}"


@dataclass
class Trace:
    trace_id: str
    ts: str
    schema_version: str = TRACE_SCHEMA_VERSION
    code_version: str = ""

    # --- request ---
    question: str = ""
    corpus: str = ""
    surface: str = "cli"              # cli | web | traffic-gen | replay

    # --- retrieval config, everything needed to reproduce the search ---
    chunking: dict = field(default_factory=dict)
    collection: str = ""
    top_k: int = 0
    candidate_k: int = 0
    use_reranker: bool = True
    use_hybrid: bool = True
    prefer_recent: bool = True
    where: dict | None = None
    min_cosine: float = 0.0
    min_rerank_score: float = 0.0

    # --- retrieval result ---
    retrieved: list = field(default_factory=list)   # chunk_id + all scores, in order
    candidates: int = 0
    keyword_only_candidates: int = 0

    # --- generation ---
    prompt_version: str = ""
    prompt_sha: str = ""
    context_sha: str = ""             # hash of the assembled CONTEXT block
    provider: str = ""
    model: str = ""
    params: dict = field(default_factory=dict)
    raw_output: str | None = None     # exactly what the model returned, pre-processing

    # --- outcome ---
    gate: str = ""                    # which gate fired: none | cosine | rerank | model | citation
    gate_detail: str = ""
    grounded: bool = False
    mode: str = ""
    answer: str = ""                  # what the user saw
    citations: list = field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None


def _write(trace: Trace) -> None:
    """Redact, then append. In that order — see the module docstring."""
    row = redact.scrub_deep(asdict(trace))
    TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def record(**kwargs) -> Trace:
    trace = Trace(
        trace_id=kwargs.pop("trace_id", None) or new_trace_id(),
        ts=kwargs.pop("ts", None) or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        code_version=code_version(),
        **kwargs,
    )
    if os.environ.get("TRACE_DISABLED", "").strip() not in ("", "0", "false"):
        return trace
    _write(trace)
    return trace


def read_all(path: Path = TRACE_FILE) -> list[dict]:
    """Every trace on disk, oldest first. Malformed lines are reported, not skipped
    silently — a truncated trace file that quietly loses rows would corrupt the sample."""
    if not path.exists():
        return []
    rows, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    if bad:
        print(f"! {bad} malformed line(s) in {path} — excluded from the population")
    return rows
