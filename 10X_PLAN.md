# 10× plan — a hailstorm week (18,000 FNOLs)

The brief: *what breaks first at catastrophe-event volume, named, with the number that proves it.*
Everything below is measured on this system unless it says **assumed** or **not measured**.

**Assumptions I had to make.** The brief gives 18,000 FNOLs for the week and nothing else. I have
assumed "1×" is about 1,800 a week and that arrivals are front-loaded (three arrival shapes are
shown, because the shape changes the answer). Provider limits on a *paid* tier are **not measured**.

## 1. Unit economics (one claim, n = 61 clean runs on `gemini-3.5-flash-lite`)

| | per claim | × 18,000 |
|---|---|---|
| LLM requests | 7.4 (6 minimum) | 132,800 |
| tokens | 22,000 (95% are prompt) | 396 M |
| cost | $0.0038 | **$68** |
| wall time | mean 30 s, p95 54 s | 151 h on one worker |
| of which model time / tool time | 25.7 s / 0.8 s | |

Cost is not the problem. Sources: `traces/capstone_traces.jsonl`, `eval/capstone_results_v*.json`.

## 2. What breaks first — in the order it breaks

**① The model provider's limit — at claim ~61 of 18,000.** On 2026-10-09 the free tier accepted
**454 requests** (≈ 61 claims) and then returned 429 on every call. At that rate 18,000 claims take
**292 days**. To clear the week the quota has to carry 13 req/min and 39k tokens/min if the work
is spread evenly, **46 req/min and 138k tokens/min if half arrives in the first day**, 92 req/min and
275k tokens/min if all of it does. Whether any paid tier does is **not measured** — it must be
confirmed with the vendor before the event, not during.

**② When ① happens, claims vanish. (S15, measured — fixed 2026-10-09, see §3.1.)** During the outage today, 10 of 10
runs (9 distinct claims) ended with **no referral at all**: nothing in `referrals.jsonl`, nothing for an adjuster.
The "every run ends in a referral" backstop only fires after `lookup_policy` has set the loss date,
and with the model down the agent never gets that far. Each claim also burned its full 240 s wall
budget on a dead provider (10 runs ≈ 40 minutes for 0 tokens). In a hailstorm this is the real
first failure: not slowness, silent loss. Fix and test are described in §3.

**③ The runner is serial.** `run_many` processes claims one after another: **119 claims/hour**,
6.3 days for 18,000. Needed workers: 0.9 if arrivals are spread evenly, **3.2 if half land in 24 h,
6.3 if all do**. No concurrent-claim path has been written or tested.

**④ The latency tail.** 5% of model calls take over 20 s and account for **48% of all model time**
(p50 call 1.5 s, max 41 s). Under rate-limit pressure that tail grows, and the 240 s wall budget
turns slow claims into failed ones.

## 3. The plan, in order

1. **S15 — half done.** *Done:* the host's forced referral now fires even when the loop never
   reached `lookup_policy` (it needs only the claim number), guarded by
   `tests/test_triage_provider_outage.py` against a provider that always fails. Verified with a stub
   provider; not re-run live. *Still open:* stop paying 240 s per claim for a dead provider — after
   three consecutive provider failures, skip the model and refer straight away with
   `triage_incomplete`.
2. **Buy and confirm quota** against the §2 figures (46 req/min and 138k tokens/min is the
   planning number), and put the numbers in the runbook.
3. **Add a bounded worker pool**: 6 workers (3.2 for the front-loaded case, plus headroom for the
   p95), all sharing the **one** policy-wording server. Queue with retry and a dead-letter list for
   anything that exhausts retries; dead-lettered claims still get a `triage_incomplete` referral.
4. **Cut tokens, not just wait**: 95% of tokens are prompt because the whole transcript is resent
   each lap. Trimming that is the largest lever on both the token quota and cost; I have not
   measured how much it saves, so no figure is claimed.
5. **Order the queue.** Every claim ends as a referral — 18,000 of them. The packet carries no
   priority, so adjusters would receive a flat list. Severity or injury flags are the first thing
   an adjuster team would ask for. Adjuster capacity is the true bottleneck and is **not measured**.

## 4. What does not break (also measured)

- **The MCP hop.** `eval/load_probe.py`: one policy-wording process answers **4.1 searches/s
  sequentially and 4.6/s with 24 in flight** — concurrency adds only 14% because the server
  serializes. At 6.3 workers the load is 0.3 searches/s, **7% of that ceiling**; with 24 requests
  queued, p50 wait was 4.5 s. Fine at the planned scale, but do **not** give each worker its own
  server: one wording process holds **1.26 GB** (embedder + reranker), so 6 would be ~7.5 GB.
- **Logs.** About 11.4 KB per claim (host trace + MCP spans): **205 MB** for 18,000.
- **Cost**, as above: $68.

## 5. Not measured, said plainly

Paid-tier rate limits · real arrival shape · adjuster throughput · behaviour of one shared MCP
session under concurrent *claims* (only concurrent searches were probed) · memory growth over a long
run · results on a model other than `gemini-3.5-flash-lite`.
