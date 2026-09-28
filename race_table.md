# Week 10 race table — single agent vs manager+2-worker orchestrator

Same 10 claims (C-001 .. C-010, `eval/race_cases.yaml`), same grading rule (`grade()` in this file, copied byte-for-byte from `eval/race.py`): status must match, and where gold status is PAYABLE the amount must match within 1 rupee.

| metric | single agent (react_agent.py) | orchestrator (manager + 2 workers) |
|---|---:|---:|
| pass rate | 8/10 = 80% | 6/10 = 60% |
| p50 latency (s) | 53.83 | 15.75 |
| p99 latency (s) | 114.98 | 22.53 |
| total tokens (10 claims) | 203,301 | 22,379 |
| cost per claim (USD) | $0.00354 | $0.00043 |
| (context) total cost, 10 claims | $0.03540 | $0.00434 |

**Context re-send multiplier**: 0.1x (orchestrator total tokens / single-agent total tokens = 22,379 / 203,301).

Single largest token share: **facts_worker -> coverage_worker**, 61% of every token the orchestrator spent across all 10 claims — see `handoffs.log` for the per-claim, per-hand-off breakdown this number is computed from.

