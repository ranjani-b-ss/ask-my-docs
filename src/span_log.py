"""Week 12 — one span format, written by every process that touches a request.

Seam S7 (SEAMS.md): the agent path had no trace id and the MCP servers wrote an unrelated log, so
nothing could follow one request across agent -> tool -> MCP server. A trace id is minted once,
at the entry point, handed to every tool call, and written on every span here — by the host AND by
each MCP server process. ``cli.py trace <id>`` stitches them back together.

Two files, same row shape:
    traces/capstone_traces.jsonl      one row per request, written by the host (spans nested)
    traces/capstone_mcp_spans.jsonl   one row per tool call, written by the server that ran it

Everything is redacted BEFORE it is written (``redact.scrub_claimant_deep``): the unredacted
string is never on disk. Claim and policy numbers are kept — they are the join key, not the
client's PII line (names, addresses, injuries).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from . import redact

ROOT = Path(__file__).resolve().parent.parent
TRACES_FILE = ROOT / "traces" / "capstone_traces.jsonl"
MCP_SPANS_FILE = ROOT / "traces" / "capstone_mcp_spans.jsonl"


def new_trace_id() -> str:
    """Random, not sequential: sequential ids leak volume (same reasoning as src/trace.py)."""
    return f"cap_{uuid.uuid4().hex[:12]}"


# Values this system generated itself. Never free text, never PII, and the keys the logs are
# searched and stitched by — so they bypass the redactor entirely rather than trusting every
# pattern in it to leave them alone.
STRUCTURAL_KEYS = frozenset({
    "trace_id", "referral_id", "claim_number", "policy_number", "chunk_id", "chunk_ids",
    "prompt_sha", "prompt_version", "document_id", "version", "effective_date", "loss_date",
    "resolved_against", "tool", "tools_discovered", "source", "server", "ts", "model",
    "retrieved_context", "stop_reason", "submitted_by", "system",
})


def append(row: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = redact.scrub_claimant_deep(row, STRUCTURAL_KEYS)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(clean, ensure_ascii=False, default=str) + "\n")


def server_span(server: str, tool: str, trace_id: str, started: float, args: dict,
                result_summary: dict, error: str | None = None) -> None:
    """Called by an MCP server process after it has handled one call."""
    append({
        "trace_id": trace_id or None,
        "source": f"mcp:{server}",
        "tool": tool,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "args": args,
        "result": result_summary,
        "error": error,
    }, MCP_SPANS_FILE)


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_logged(server: str, tool: str, trace_id: str, args: dict, fn, summarize):
    """Run one tool call and write its span — also when it raises, so a failing call is
    visible in the trace instead of leaving a hole where the span should be."""
    started = time.perf_counter()
    try:
        result = fn()
    except Exception as exc:                                       # noqa: BLE001 — re-raised
        server_span(server, tool, trace_id, started, args, {}, error=f"{type(exc).__name__}: {exc}")
        raise
    server_span(server, tool, trace_id, started, args, summarize(result))
    return result


def stitch(trace_id: str) -> dict:
    """Join one request's host trace and the spans each MCP server wrote for it.

    ``complete`` is the number that answers "did one trace id survive every hop": for every tool
    the host dispatched, the server that ran it must have written a span carrying the same id.
    """
    host_rows = [r for r in read(TRACES_FILE) if r.get("trace_id") == trace_id]
    host = host_rows[-1] if host_rows else None
    server = [r for r in read(MCP_SPANS_FILE) if r.get("trace_id") == trace_id]
    host_calls: dict[str, int] = {}
    for sp in (host or {}).get("spans", []):
        if sp.get("kind") == "tool" and not sp.get("blocked"):
            host_calls[sp["tool"]] = host_calls.get(sp["tool"], 0) + 1
    server_calls: dict[str, int] = {}
    for sp in server:
        server_calls[sp["tool"]] = server_calls.get(sp["tool"], 0) + 1
    hops = [{"tool": t, "host_calls": n, "server_spans": server_calls.get(t, 0),
             "matched": server_calls.get(t, 0) == n} for t, n in sorted(host_calls.items())]
    return {"host": host, "server_spans": server, "hops": hops,
            "complete": bool(hops) and all(h["matched"] for h in hops)}
