"""Week 12 — load probe for the MCP hop, no model involved (10x plan, hailstorm week).

Question: when several claims are in flight at once, does the policy-wording server keep up?
It is one process on one stdio pipe, so this measures the ceiling before any LLM is added.

  python eval/load_probe.py            # 24 searches sequentially, then 24 at once

Searches carry trace_id "loadtest"; the rows they leave in traces/capstone_mcp_spans.jsonl are
removed at the end (exact trace_id match), so the probe leaves the real logs as it found them.
"""

import asyncio
import json
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import span_log                                                    # noqa: E402
from src.agent.mcp_client import MCPToolRegistry, load_config               # noqa: E402
from src.agent.triage_agent import DEFAULT_CONFIG, _absolutise              # noqa: E402

QUERIES = [
    "compulsory deductible for engine capacity", "outside the geographical area stated in the schedule",
    "under the influence of intoxicating liquor", "used for hire or reward",
    "co-payment for insured persons aged above sixty", "room rent limit per day",
    "tyre replacement when the vehicle is also damaged", "waiting period for pre-existing conditions",
    "mechanical or electrical breakdown", "constructive total loss threshold",
    "settlement timeline after final documents", "grievance response time",
]
N = 24


def q(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def rss_mb(match: str) -> float:
    out = subprocess.run(["ps", "-axo", "rss,command"], capture_output=True, text=True).stdout
    return sum(int(line.split(None, 1)[0]) for line in out.splitlines() if match in line) / 1024


async def one(registry: MCPToolRegistry, i: int) -> float:
    started = time.perf_counter()
    await registry.dispatch("search_wording", {
        "query": QUERIES[i % len(QUERIES)], "product": "motor" if i % 2 else "health",
        "loss_date": "2026-03-31", "top_k": 3, "trace_id": "loadtest"})
    return time.perf_counter() - started


async def main() -> dict:
    async with MCPToolRegistry(_absolutise(load_config(DEFAULT_CONFIG))) as registry:
        await one(registry, 0)                                        # warm the models
        t0 = time.perf_counter()
        seq = [await one(registry, i) for i in range(N)]
        seq_wall = time.perf_counter() - t0
        t0 = time.perf_counter()
        con = await asyncio.gather(*[one(registry, i) for i in range(N)])
        con_wall = time.perf_counter() - t0
        server_mb = rss_mb("wording_server.py")
    return {"n": N,
            "sequential": {"wall_s": round(seq_wall, 2), "p50_ms": round(q(seq, .5) * 1000),
                           "p95_ms": round(q(seq, .95) * 1000), "searches_per_s": round(N / seq_wall, 2)},
            "concurrent": {"wall_s": round(con_wall, 2), "p50_ms": round(q(con, .5) * 1000),
                           "p95_ms": round(q(con, .95) * 1000), "max_ms": round(max(con) * 1000),
                           "searches_per_s": round(N / con_wall, 2)},
            "wording_server_rss_mb": round(server_mb)}


def clean_probe_rows() -> int:
    path = span_log.MCP_SPANS_FILE
    keep, dropped = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if json.loads(line).get("trace_id") == "loadtest":
            dropped += 1
        else:
            keep.append(line)
    path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return dropped


if __name__ == "__main__":
    try:
        result = asyncio.run(main())
    finally:
        removed = clean_probe_rows()
    result["probe_rows_removed_from_log"] = removed
    (ROOT / "eval" / "load_probe_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
