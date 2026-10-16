# 10× plan — a hailstorm week (18,000 FNOLs)

The brief: *what breaks first at catastrophe-event volume, named, with the number that proves it.*
Everything below is measured on this system unless it says **assumed** or **not measured**.
Refreshed 2026-10-18 on the final system (`triage-v3` + structured chunking + exclusions gate + parser fix; the 36-case run `eval/capstone_results_v3b.json`).

**Assumptions I had to make.** The brief gives 18,000 FNOLs for the week and nothing else. I have
assumed "1×" is about 1,800 a week and that arrivals are front-loaded (three arrival shapes are
shown, because the shape changes the answer). Provider limits on a *paid* tier are **not measured**.

## 1. Unit economics (one claim, n = 36 runs of the final system, `gemini-3.5-flash-lite`)

| | per claim | × 18,000 |
|---|---|---|
| LLM requests | 7.6 (6 minimum) | 136,500 |
| tokens | 25,400 mean · 27,300 median · 33,000 p90 (95% are prompt) | 458 M |
| cost | $0.0044 (was $0.0038 before the gate) | **$79** |
| wall time | median 64 s, mean 79 s, p95 219 s | 395 h on one worker (16 days) |
| model time / tool time | tools are **1–3% of the wall time** in every run | |

**Wall time is the unstable number.** The same system measured 25 s median (v2), 44 s (v3) and 64 s (v3b); the per-call model latency went 1.5 s → 1.8 s → **4.5 s** median
while the work per claim stayed the same (7.6 requests), so most of the growth is the provider, not the code — but I cannot separate network, machine and rate-limit back-off,
and the runs were on different days and machines. Capacity below is therefore a **range**, not a point. Cost and token figures were stable.

Cost is not the problem. Sources: `traces/capstone_traces.jsonl`, `eval/capstone_results_v*.json`.

## 2. What breaks first — in the order it breaks

**⓪ The per-claim token budget — already broken at 1×.** The budget is 30,000 tokens. The median claim now uses 27,300 and the 90th percentile 33,000, so
**6 of 36 runs stopped on the budget** (CLM-2026-00468, -00479, -00483, -00502, -00533, -00548) — and **5 of those 6 still passed every assertion**, because a forced
referral with some citations satisfies them. The eval does not see a packet that never finished. The cause is mostly structural: 95% of tokens are prompt because every
retrieved chunk is resent on every later lap, and the exclusions gate adds a search whose chunks ride along. This is not a volume problem — it needs fixing before volume
(SEAMS.md S23).

**① The model provider's limit — at claim ~61 of 18,000.** On 2026-10-09 the free tier accepted
**454 requests** (≈ 61 claims) and then returned 429 on every call. At that rate 18,000 claims take
**~300 days**. It recurred: a single 36-claim run needs ~273 requests, which fits only on an otherwise unused day (it did not on 2026-10-13/14). To clear the week the quota has to
carry **14 req/min and 45k tokens/min** if the work is spread evenly, **47 req/min and 159k tokens/min if half arrives in the first day**, 95 req/min and 318k tokens/min if all
of it does. Whether any paid tier does is **not measured** — it must be confirmed with the vendor before the event, not during.

**② When ① happens, claims vanish. (S15, measured — fixed 2026-10-09, see §3.1.)** During the outage, 10 of 10
runs (9 distinct claims) ended with **no referral at all**: nothing in `referrals.jsonl`, nothing for an adjuster.
The "every run ends in a referral" backstop only fired after `lookup_policy` had set the loss date,
and with the model down the agent never got that far. Each claim also burned its full 240 s wall
budget on a dead provider (10 runs ≈ 40 minutes for 0 tokens). In a hailstorm this is the real
first failure: not slowness, silent loss. The referral is fixed (every later outage run still produced one); the 240 s wait is not.

**③ The runner is serial.** `run_many` processes claims one after another: **46 claims/hour at this run's latency** (119/hour at v2's), i.e. **16 days** (6 days) for 18,000.
Workers needed, by arrival shape — *final-system timings → best case at v2 timings*:

| arrivals | claims/hour | workers |
|---|---|---|
| spread over the week | 107 | 2.3 → 1.0 |
| half in the first 24 h | 375 | **8.2 → 3.6** |
| all in 24 h | 750 | 16.4 → 7.1 |

No concurrent-claim path has been written or tested.

**④ The latency tail.** In the final run 27 of 273 model calls took over 20 s and account for **51% of all model time** (p50 call 4.5 s, p90 19.9 s); in v2 it was 10 of 262
calls and 46%. Under rate-limit pressure that tail grows, and the 240 s wall budget turns slow claims into failed ones (the slowest valid claim took 253 s).

## 3. The plan, in order

1. **S15 — half done.** *Done:* the host's forced referral fires even when the loop never reached
   `lookup_policy` (it needs only the claim number), guarded by `tests/test_triage_provider_outage.py`; confirmed live by later outage runs, each of which still got a referral.
   *Still open:* stop paying 240 s per claim for a dead provider — after three consecutive provider failures, skip the model and refer straight away with `triage_incomplete`.
   (The eval runner already stops itself after two no-reply claims; the agent does not.)
2. **Fix the token budget first (⓪).** Either raise the 30,000 limit, or stop resending every retrieved chunk each lap. Trimming the transcript is the larger lever on both the token
   quota and cost; I have not measured how much it saves, so no figure is claimed.
3. **Buy and confirm quota** against the §2 figures (**47 req/min and 159k tokens/min** is the planning number for a front-loaded week), and put the numbers in the runbook.
4. **Add a bounded worker pool**: plan for **8 workers** for the front-loaded case on today's latency (4 if latency returns to v2's), all sharing the **one** policy-wording server.
   Queue with retry and a dead-letter list for anything that exhausts retries; dead-lettered claims still get a `triage_incomplete` referral.
5. **Order the queue.** Every claim ends as a referral — 18,000 of them. The packet carries no priority, so adjusters would receive a flat list. Severity or injury flags are the
   first thing an adjuster team would ask for. Adjuster capacity is the true bottleneck and is **not measured**.

## 4. What does not break (measured)

- **The MCP hop.** `eval/load_probe.py` (measured on the earlier system): one policy-wording process answers **4.1 searches/s sequentially and 4.6/s with 24 in flight** — concurrency
  adds only 14% because the server serializes. At 16 workers the load is ~0.3 searches/s (16.4 workers ÷ 79 s × 1.28 searches per claim), **about 6% of that ceiling**; do **not**
  give each worker its own server: one wording process holds **1.26 GB** (embedder + reranker), so 8 would be ~10 GB.
- **Tools are 1–3% of every run's time** — the time is the model, not retrieval or the claims server.
- **Logs.** About 11.4 KB per claim (host trace + MCP spans) → **~205 MB** for 18,000. Measured on the earlier runs; not re-measured.
- **Cost**, as above: **$79** for the week.

## 5. Not measured, said plainly

Paid-tier rate limits · real arrival shape · adjuster throughput · behaviour of one shared MCP session under concurrent *claims* (only concurrent searches were probed) · memory growth
over a long run · results on a model other than `gemini-3.5-flash-lite` · why model latency tripled between runs (provider, network, machine or throttling) · the MCP load probe and
log size were not repeated on the final system.
