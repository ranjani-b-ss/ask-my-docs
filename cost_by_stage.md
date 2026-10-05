# Week 11 — cost per query, broken down by stage

Real numbers from the RED suite run (`eval/run_claim_suite.py`, 11 claims, all real
`react_agent.run()` calls on `gemini-3.5-flash-lite` — see `tenx.md` for why not the
pinned model today). Every claim now logs `stage_seconds`/`stage_cost_usd` split
retrieval / generation / tools — this table is a straight sum across all 11.

| stage | wall time | share of wall time | cost |
|---|---:|---:|---:|
| retrieval (`search_policy` — local ONNX embed + rerank) | 17.30s | 5.6% | $0.00000 |
| generation (every `usage.call_llm` call) | 289.76s | 94.4% | $0.03821 |
| tools (`get_claim`, `compute_payout` — in-process) | 0.003s | ~0.0% | $0.00000 |
| **total** | **307.06s** | **100%** | **$0.03821** |

**Cost per query: $0.00347 average** (11 claims, $0.03821 / 11). Every cent of it is
generation — this architecture's retrieval and tool stages are free local compute, so
"cost per query" and "generation cost per query" are the same number here by construction,
not by coincidence. That's worth stating plainly rather than implying a 3-way split that
doesn't actually exist in this app's cost structure.

**Where the money actually goes, one level deeper**: `usage.py`'s own long-documented
property — the ReAct loop resends its whole growing transcript every lap — means a claim
that needs more laps doesn't cost proportionally more, it costs *super-linearly* more. The
drill's own planted claim (C-011) is the sharpest illustration sitting right in this same
batch: 8 laps, 33,463 tokens, $0.00609 — the single most expensive claim in the batch (see
`drill.md`), almost entirely because repeated failed searches kept growing the transcript
every one of those 8 laps resent in full. **A cheap fix at the right layer (teaching lap 1's
query to find the right chunk) is also a cost fix** — not a separate concern from
correctness.

**6.5 LLM calls per claim, on average** — not 1. "Cost per query" undercounts by close to
6.5x if read as "cost of one model call" instead of "cost of the whole multi-lap decision"
— the number above is the latter, the one that actually bills.
