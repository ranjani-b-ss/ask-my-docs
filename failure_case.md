# Week 10 — injected worker failure on C-004

**What was injected**: `orchestrator._coverage_worker` raised a simulated HTTP 500 (`WorkerError`) on every call for claim C-004, standing in for the coverage/exclusions worker's backend being down.

**What the orchestrator actually did**: retried once (a stateless retry against a deterministic fault fails identically — `worker_error` below is the same message twice), then **degraded to a safe REFERRED** rather than guessing at coverage or declaring the claim covered with no exclusions check. It did not lie.

- `degraded`: `True`
- `worker_error`: `coverage_worker returned 500: simulated backend outage (injected)`
- final status: `REFERRED` (gold: `NOT_PAYABLE`)
- rationale returned to the claims lead: "coverage/exclusions worker failed twice (coverage_worker returned 500: simulated backend outage (injected)); referring this claim rather than guessing at a coverage decision with no exclusions check completed."

Behavior in one line: **degraded to a partial (REFERRED) answer, honestly labeled as a worker outage — did not retry indefinitely, did not fabricate a coverage decision.**

