# Week 10 race table — single agent vs manager+2-worker orchestrator

Same 10 claims (C-001 .. C-010, `eval/race_cases.yaml`), same grading rule (`grade()` in this file, copied byte-for-byte from `eval/race.py`): status must match, and where gold status is PAYABLE the amount must match within 1 rupee.

| metric | single agent (react_agent.py) | orchestrator (manager + 2 workers) |
|---|---:|---:|
| pass rate | 7/10 = 70% | 1/10 = 10% |
| p50 latency (s) | 142.44 | 596.83 |
| p99 latency (s) | 312.27 | 671.21 |
| total tokens (10 claims) | 162,247 | 14,687 |
| cost per claim (USD) | $0.00000 | $0.00000 |
| (context) total cost, 10 claims | $0.00000 | $0.00000 |

**Context re-send multiplier**: 0.1x (orchestrator total tokens / single-agent total tokens = 14,687 / 162,247).

Single largest token share: **manager -> facts_worker**, 48% of every token the orchestrator spent across all 10 claims — see `handoffs.log` for the per-claim, per-hand-off breakdown this number is computed from.

