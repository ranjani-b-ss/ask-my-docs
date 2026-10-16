#!/usr/bin/env python
"""Week 12 bonus — the loss-date filter, end to end: the same claims through the agent with the filter ON and OFF.

    python eval/run_straddle_ablation.py --runs 2

OFF = WORDING_DATE_FILTER=off in the wording server (mcp_config_capstone_nofilter.json): `search_wording` ignores the
loss date and product and returns the best wording of ANY date — what retrieval did before Week 12. Everything else is
identical: same prompt, same model, same claims-system server, same superseded-clause marker. Only the filter differs.

DEFINITIONS, written before any run (so they cannot be adjusted to the result):
  exposure   a run is EXPOSED if any chunk the model was shown comes from a document whose effective_date is AFTER the
             loss date. Independent of what the model then does — it measures what the filter keeps out of context.
  RED        the packet CITES a chunk from a document not yet in force on the loss date — the failure the date filter exists
             to prevent. GREEN = it does not.
  claims     five whose loss PRECEDES an endorsement that restates or amends the clause asked about (the date filter should
             matter): 601, 607, 609 (the day before), 437, 442 (weeks before). Two controls whose loss is ON the effective
             day (602, 608), where both versions are in force and the filter should make no difference.
  runs       the two conditions are interleaved claim by claim, so a quota stop cannot bias one of them.
One run per cell is a sample of a stochastic system; the table reports counts out of n, not rates of a fixed behaviour.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import run_capstone_eval as rce                                    # noqa: E402
from src import cap_assertions, claim_files                         # noqa: E402
from src.agent import triage_agent as ta                            # noqa: E402
from src.agent.mcp_client import MCPToolRegistry, load_config        # noqa: E402

BEFORE = ["CLM-2026-00601", "CLM-2026-00607", "CLM-2026-00609", "CLM-2026-00437", "CLM-2026-00442"]
CONTROLS = ["CLM-2026-00602", "CLM-2026-00608"]
CONFIGS = {"on": ROOT / "mcp_config_capstone.json", "off": ROOT / "mcp_config_capstone_nofilter.json"}


def classify(result: dict, loss_date: str, docs: dict) -> dict:
    shown = {cid.split("::")[0] for cid in (result.get("retrieved_context") or {})}
    exposed = sorted(d for d in shown if docs.get(d, {}).get("effective_date", "0000") > loss_date)
    cited = sorted({w["document_id"] for w in result["packet"].get("wording", [])
                    if docs.get(w["document_id"], {}).get("effective_date", "0000") > loss_date})
    return {"exposed_to": exposed, "cited_not_yet_in_force": cited}


async def main(runs: int, model: str, out: Path) -> None:
    docs = cap_assertions.corpus_documents()
    rows = json.loads(out.read_text()) if out.exists() else []
    done = {(r["claim"], r["condition"], r["run"]) for r in rows}
    order = [(c, r) for r in range(1, runs + 1) for c in BEFORE + CONTROLS]
    servers = {k: ta._absolutise(load_config(v)) for k, v in CONFIGS.items()}
    async with MCPToolRegistry(servers["on"]) as reg_on, MCPToolRegistry(servers["off"]) as reg_off:
        regs = {"on": reg_on, "off": reg_off}
        for reg in regs.values():
            await ta.warm_up(reg)
        for claim, run in order:
            for cond in ("off", "on"):                                  # off first: if quota stops, ON is not favoured
                if (claim, cond, run) in done:
                    continue
                result = await ta.run_with_registry(regs[cond], claim, model=model,
                                                    submitted_by=f"straddle-ablation-{cond}")
                scored = rce.score(result)
                cf = claim_files.get(claim)
                row = {"claim": claim, "kind": "before" if claim in BEFORE else "control", "loss_date": cf.loss_date,
                       "condition": cond, "run": run, "trace_id": result["trace_id"],
                       "stop_reason": result["stop_reason"], "tokens": result["usage"]["total_tokens"],
                       "all_passed": scored["all_passed"],
                       "failed": [k for k, a in scored["assertions"].items() if not a["passed"]],
                       **classify(result, cf.loss_date, docs)}
                rows.append(row)
                out.write_text(json.dumps(rows, indent=1))
                tag = "RED" if row["cited_not_yet_in_force"] else "green"
                print(f"{claim} run{run} filter={cond:<3} exposed={bool(row['exposed_to'])!s:<5} {tag:<5} "
                      f"cites_future={row['cited_not_yet_in_force']} tokens={row['tokens']} stop={row['stop_reason'][:20]}",
                      flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--out", default=str(ROOT / "eval" / "straddle_ablation_results.json"))
    a = ap.parse_args()
    asyncio.run(main(a.runs, a.model, Path(a.out)))
