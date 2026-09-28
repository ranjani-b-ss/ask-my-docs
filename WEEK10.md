# Week 10 — Multi-Agent & A2A: With Evidence, Not Fashion

## Task Set D · Insurance claims · Race the claims squad against the single agent

Every number below came from a real, fresh run of both systems against the same 10 claims
today — nothing here is asserted without `race_table.md`, `handoffs.log`,
`race_multiagent_raw.json`, or `failure_case.md` to back it. `eval/race_multiagent.py` is the
one script that produced all four; this file explains what they show and why.

---

## 1. The numbers, up front (Race 1 — initial build)

| metric | single agent (`react_agent.py`) | orchestrator (manager + 2 workers) |
|---|---:|---:|
| pass rate | **8/10 = 80%** | **4/10 = 40%** |
| p50 latency | 31.62s | 14.79s |
| p99 latency | 157.31s | 34.47s |
| total tokens (10 claims) | 138,654 | 18,808 |
| cost per claim | $0.00246 | $0.00037 |

**Context re-send multiplier: 0.1x** — the orchestrator used *fewer* tokens overall, not
more. §4 explains why, because that's the opposite of what the brief's own "common
mistakes" list warns to expect.

**These are Race 1's numbers**, before the deductible-query fix described in §8. §8 has the
current, superseding race table and the current verdict — read it, not just this section,
before quoting a pass rate from this file. `race_table.md` and `verdict.md` on disk always
hold the *latest* race; this section is kept as the honest record of what Race 1 actually
showed, not silently overwritten.

**Race 1's verdict was: kill the team, keep the single agent.** §8 re-races after a real fix
and reaches the same verdict for a different reason — see there before treating this as
final.

A methodology note before anything else: this key's pinned model (`gemini-3.6-flash`) turned
out to have a **20-requests-per-day free-tier ceiling**, confirmed from the 429 body itself
(`quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier`) and already exhausted partway
through building this race. Both arms were re-run on `gemini-3.5-flash-lite` instead — a
separate quota bucket — passed explicitly via `--model` to `eval/race_multiagent.py` so it's
visible in the command, not silently changed in `.env`. Both arms always get the *same*
model; a race is not fair if one side runs a different model than the other.

---

## 2. Architecture: one manager, two narrow specialists, a fixed pipeline

```
src/agent/orchestrator.py       manager + 2 workers, a fixed 4-call pipeline, not a loop
src/agent/react_agent.py        the single agent — unchanged, this week's baseline
eval/race_multiagent.py         runs both arms on eval/race_cases.yaml's 10 claims,
                                 grades with the same rule eval/race.py already uses
```

Call order, always:

1. **manager_decompose** — task-level only ("claim id: C-004"), no claim data yet, so this
   one call carries none of the resend cost the rest of the pipeline does.
2. **facts_worker** — reads the claim file (`get_claim`, unchanged), summarises the
   risk-relevant facts and writes ONE search query for the next specialist.
3. **coverage_worker** — resends that summary, calls `search_policy` itself with the
   query it was handed, and decides PAYABLE / NOT_PAYABLE / REFERRED plus the deductible.
4. **manager_synthesize** — resends the facts summary and the coverage decision, writes
   the client-facing rationale. It copies the status and amount; it does not re-derive them.

`compute_payout` is called directly by the pipeline code, the same deterministic tool
`react_agent.py` uses — there is nothing for a fifth LLM call to decide once status,
claim_amount and deductible are all known, and routing arithmetic through a model call would
only inflate the bill for no reason.

Two things deliberately **not** done, because the brief's own mistakes list warns against
exactly them:

- The coverage worker has `search_policy` and nothing else — not `get_claim`, not
  `compute_payout`. Handing it the single agent's full toolset would delete the one
  plausible source of a win (a narrower prompt, fewer tools per call) before the race even
  started.
- No new eval set. `eval/race_cases.yaml` — the same 10 motor claims and gold answers
  `eval/race.py` already uses — is the only ruler either arm is measured against.

---

## 3. Requirement 3 — where the orchestrator's tokens actually go

| hand-off | total tokens (10 claims) | share |
|---|---:|---:|
| facts_worker -> coverage_worker | 10,132 | **54%** |
| manager -> facts_worker | 4,710 | 25% |
| coverage_worker -> manager (synthesis) | 2,439 | 13% |
| manager decompose | 1,527 | 8% |

**facts_worker -> coverage_worker is the dominant hand-off**, at 54% of every token the
team spent — see `handoffs.log` for the full per-claim breakdown this is aggregated from.
It's the one call carrying the retrieved policy passages (up to 3 chunks of clause text),
which is the same reason `search_policy`'s own results are the single biggest line item in
`react_agent.py`'s transcript too — retrieved text is expensive wherever it lands.

---

## 4. Requirement 2 — why the multiplier went the "wrong" way

The brief expects multi-agent to cost *more*: "every hand-off re-sends everything." That's
true *within* the orchestrator — hand-off 3 above proves it. But the comparison that
actually matters is against the single agent, and `react_agent.py` pays a much larger
version of the exact same tax on itself: **it resends its own growing transcript on every
lap of its ReAct loop** (documented in `usage.py` since Week 7 — "lap 4 pays for the text of
laps 1 through 3 all over again"). Some claims took the single agent 5-8 laps; the
orchestrator is a fixed 4 calls, each short, with no accumulating transcript at all.

The result: **18,808 tokens for the team vs 138,654 for the single agent — the team used
7.4x fewer tokens**, not more. This is a real finding, and also a narrow one: it says a
fixed-depth pipeline of short specialist calls beats an open-ended resend-everything loop on
*tokens*, not that multi-agent beats single-agent in general. A single agent that didn't
resend its whole transcript every lap (a real multi-turn session, if the underlying `chat()`
primitive supported one) would likely close most of this gap without needing a team at all.

---

## 5. Requirement 1 — same 10 claims, same grading rule, and why the team lost anyway

`eval/race_multiagent.py:grade()` is copied byte-for-byte from `eval/race.py:grade()`:
status must match, and where gold is PAYABLE the amount must match within a rupee. Full
per-claim comparison in `race_multiagent_raw.json`; the pattern in the misses is not noise:

| claim | gold | orchestrator | what actually happened |
|---|---|---|---|
| C-001 | PAYABLE/7000 | PAYABLE/**8000** | deductible defaulted to 0 — no deductible search happened |
| C-002 | PAYABLE/12000 | PAYABLE/**15000** | same — deductible defaulted to 0 |
| C-007 | PAYABLE/33000 | PAYABLE/**40000** | deductible defaulted to 0 **and** the hire-car exclusion was never subtracted — a second, compounding gap, see below |
| C-008 | PAYABLE/4000 | PAYABLE/**5000** | same — deductible defaulted to 0 |
| C-009 | NOT_PAYABLE/0 | **PAYABLE**/65000 | missed the mechanical-breakdown exclusion entirely |
| C-004 | NOT_PAYABLE/0 | **REFERRED** | `search_policy` returned health-policy passages, not motor — wrong corpus hit |
| C-010 | REFERRED | REFERRED ✓ | **the one case the team got right and the single agent didn't** |

**Four of five real misses are one bug, not five different problems**: the facts worker's
one search query is built to surface *exclusion*-relevant facts; nothing in the pipeline
ever asks a second, differently-worded question for the deductible figure the way
`react_agent.py`'s own system prompt requires (rule 4: "never state a deductible figure you
have not actually retrieved"). The coverage worker gets exactly one retrieval shot from a
query it didn't choose, and when that query doesn't happen to surface a deductible passage,
`decision.get("deductible") or 0.0` silently pays the claim in full. This is the concrete
shape of "narrower prompt, fewer tools" cutting the wrong way: the single agent's ReAct loop
can notice a search came back thin and search again; this fixed pipeline cannot retry
anything.

C-007 has a second, distinct gap layered on top of the first: `react_agent.py`'s rule 5
("exclude only the uncovered part before computing the payout") has no equivalent anywhere
in the orchestrator's decision schema — `_coverage_worker`'s JSON has a `status` and a
`deductible`, nothing for "and only pay against $34,000 of the claimed $40,000." Even with a
correctly-retrieved deductible, this pipeline would have paid $39,000 against the full
claimed amount, not gold's $33,000. This was never noticed or worked around; it's reported
here because it's real, not because §5's table needed a second bug to make its point.

C-004 is the same root cause from a different angle — one query, one search, no chance to
notice the passages were off-topic and try again. C-009 is a reasoning miss, not a retrieval
one: the facts summary correctly named "internal transmission failure, no external impact,"
which is close to Clause 3's exact wording, and the coverage worker still didn't flag it.

C-010 is the one genuine win, reported evenhandedly: it's the deliberately ambiguous
flood-vs-mechanical-failure claim, and the coverage worker's narrower framing (and its
explicit "reserve REFERRED for a fact that's missing" instruction) referred it correctly
where the single agent overclaimed a confident NOT_PAYABLE. One win out of ten does not
change the verdict.

---

## 6. Requirement 4 — the injected worker failure

`eval/race_multiagent.py --failure-case C-004` forces `orchestrator._coverage_worker` to
raise a simulated HTTP 500 on every call for that claim — the coverage/exclusions worker's
backend, down. Full transcript in `failure_case.md`; the short version:

- The orchestrator **retried once** (a stateless retry against a deterministic fault fails
  identically — `worker_error` is logged as the same message both times).
- It then **degraded to a safe REFERRED**, honestly labeled: `degraded: true`,
  `worker_error` naming the exact failure, and a rationale that says outright "referring
  this claim rather than guessing at a coverage decision with no exclusions check
  completed."
- It did **not** retry indefinitely, and it did **not** declare the claim covered with no
  exclusions check — the one behavior this requirement most wants ruled out.

Kept **out of the main race numbers on purpose**: contaminating `race_table.md`'s pass rate
with a fault the single agent never faced would make the two arms' pass rates
incomparable — the same mistake as changing the eval set mid-measurement, just aimed at one
row instead of all ten.

---

## 7. What was deliberately left alone

Per this week's scope — build the team, race it, report honestly, not "fix it until it
wins" — the following are named as choices, not oversights:

- **The deductible bug was not fixed here.** It's the load-bearing finding of §5 and Race 1's
  `verdict.md`; fixing it in the same pass as measuring it would mean re-racing before the
  verdict could even be written, and the brief asks for the honest number first, not the
  flattering one. It was fixed afterward, on request — see §8.
- **No third specialist, no different decomposition.** The manager/facts/coverage split is
  the one the brief names; trying three or four different team shapes to find one that wins
  would be searching for a result, not measuring one.
- **`react_agent.py` was not touched.** It's this week's baseline exactly as Week 7 left it.

---

## 8. The deductible-query fix, and the new bug it exposed

Requested afterward, scoped to exactly one thing: fix the deductible defaulting to 0, and
re-race. Nothing else about the team changed — not the partial-exclusion gap on C-007, not
the C-009 reasoning miss, not the C-004 wrong-corpus retrieval. Those stay open, exactly as
§5 and §7 already named them.

### 8.1 What changed

`_coverage_worker` in `src/agent/orchestrator.py` used to run **one** search — the facts
worker's exclusion-focused query — and expect a deductible figure to fall out of it by
accident. It now runs a **second, dedicated** search built directly from the claim's own
structured fields (`vehicle_cc`, `date_of_loss`), the same way `react_agent.py`'s own rule 4
makes the deductible check its own mandatory step rather than a hope. `COVERAGE_SYSTEM`'s
prompt was updated to label both passage sets and to require a non-null deductible whenever
a deductible passage is present.

Verified directly, outside the race, before re-running it: querying `search_policy` with
`"compulsory deductible for a 1400cc vehicle, date of loss 2026-02-10"` (C-001's real
fields) returns **both** the base clause (PW-MOTOR-001, relevance 0.943, ranked first) and
the endorsement clause (END-2026-01, relevance 0.594) — the right passage is retrieved, and
ranked higher. The retrieval side of this fix works exactly as intended.

### 8.2 The re-race

| metric | single agent | orchestrator |
|---|---:|---:|
| pass rate | 5/10 = 50% | 4/10 = 40% |
| p50 latency | 37.08s | 15.71s |
| p99 latency | 94.44s | 61.61s |
| total tokens (10 claims) | 175,933 | 22,639 |
| cost per claim | $0.00311 | $0.00044 |

(`race_table.md` and `handoffs.log` on disk are this re-race, not Race 1 — they were
overwritten by design, same as every other week's "the latest run wins" convention.)

Context re-send multiplier: still **0.1x** (22,639 / 175,933) — the team is still cheaper
overall, for the same reason §4 gives. The dominant hand-off moved to **61%**
(`facts_worker -> coverage_worker`, up from 54% in Race 1), because that call now carries
two searches' worth of passages instead of one — the direct, expected cost of the fix.

**The silent-zero bug is confirmed gone.** Across all 10 claims, `deductible` was never
null and never silently 0 on a PAYABLE decision — a real number was retrieved and used
every time. That is exactly, and only, what was asked for.

**The pass rate did not improve — 4/10, same as Race 1 — because a different, new bug took
the old one's place.** All four PAYABLE claims (C-001, C-002, C-007, C-008) are still wrong
on amount, but now every one of them applied the endorsement's **INR 1,500** figure
specifically, regardless of whether that claim's `date_of_loss` actually falls before or
after the endorsement's 2026-04-01 effective date, and regardless of the vehicle's real cc
tier. Quoting the coverage worker's own stated reasoning, unedited:

- C-001 (1400cc, loss **2026-02-10** — before the endorsement, base 1000 should apply):
  *"subject only to the revised compulsory deductible of INR 1,500"*
- C-002 (**1800cc** — above 1500cc, loss after the endorsement, revised-tier 3000 should
  apply): *"applying the compulsory deductible of INR 1,500 mandated by Endorsement 1 for
  vehicles up to 1500cc"* — picked the endorsement correctly (date-wise), then the wrong cc
  tier within it.
- C-007 (1400cc, loss 2026-03-01 — before the endorsement, base 1000 should apply):
  *"the applicable compulsory deductible is INR 1,500 under Endorsement 1"*
- C-008 (1350cc, loss 2026-01-20 — before the endorsement, base 1000 should apply):
  *"the revised compulsory deductible of INR 1,500 applied"*

Every one of the four reaches for "INR 1,500" — the endorsement's *first-mentioned* figure —
whether or not the endorsement actually governs that claim's date. This looks like a
recency/anchoring effect, not a retrieval gap: the endorsement passage is deliberately
listed *last* in the coverage worker's prompt (exclusion passages first, then the base
deductible clause, then the endorsement clause), and "INR 1,500" is the first number that
appears inside that last passage. §8.1 already showed the base clause is retrieved and
ranked *higher* by the retriever — the coverage worker had the right passage in hand and
still didn't prefer it. This is a reasoning bug, not something the query fix touches, and it
was not chased further — that would be scope creep past what was asked.

### 8.3 A caveat worth stating plainly

The single agent's own pass rate also moved, from 80% (Race 1) to 50% (this re-race),
**despite `react_agent.py` being completely untouched between the two races.** That is real
run-to-run variance on a free-tier model, not a regression to explain — four of its claims
this run gave up with REFERRED after exhausting laps on malformed output, which didn't
happen in Race 1. Treat the pass-rate comparison as "40% vs 50%, on claims that are
themselves noisy at this sample size," not as two fixed numbers with a precise gap. The
orchestrator's own 40%, unlike the single agent's, held steady across both races — the same
four claims (C-004, C-007 [wrong in a new way], and its own PAYABLE quartet) failed both
times, which is what makes the tier-selection bug a *systematic* finding rather than noise.

### 8.4 Updated verdict (superseded by §9 — read on)

Still kill the team — see the current `verdict.md`, rewritten to reflect this section. The
reason changed, though: Race 1's verdict was "the team drops the deductible silently."
That's fixed. The team still loses because a narrow specialist call, working from a
correctly-retrieved passage, chose the wrong number inside it four times out of four — a
different failure, not a smaller one.

---

## 9. The tier-selection fix, and the honest result

Requested next, scoped again to exactly one thing: fix the tier-selection bug from §8.3,
and re-race. C-007's separate partial-exclusion gap, C-004's wrong-corpus retrieval, and any
exclusion-recognition misses stay open — not touched.

### 9.1 What changed

§8.3's bug wasn't a retrieval problem — the right passage was already being retrieved and
ranked first. It was a single narrow LLM call being asked to do a date comparison and a
cc-tier lookup from raw text, and getting both wrong in the same specific way every time
(anchoring on the endorsement's first-mentioned figure). The fix moves that lookup out of
the model entirely: `_resolve_deductible()` in `src/agent/orchestrator.py` compares each
retrieved passage's `effective_date` string against the claim's `date_of_loss` string
(ISO `YYYY-MM-DD` sorts chronologically as plain text, so no date parsing is needed), picks
whichever passage actually governs, then regex-extracts the correct cc-tier figure from
that passage's text and overrides whatever the coverage worker returned. Same reasoning as
`compute_payout`'s own existence (`react_agent.py` rule 8: "never compute the subtraction
yourself") — a lookup with exactly one right answer belongs in code, not in a small model's
free-text reasoning over two similar-looking passages.

Verified against all four of §8.3's failing claims, in isolation, before re-racing:
`_resolve_deductible` returns 1000 for C-001/C-007/C-008 (all pre-endorsement, base tier)
and 3000 for C-002 (post-endorsement, above-1500cc tier) — all four correct.

### 9.2 The re-race

| metric | single agent | orchestrator |
|---|---:|---:|
| pass rate | 8/10 = 80% | **6/10 = 60%** (up from 40% in both prior races) |
| p50 latency | 53.83s | 15.75s |
| p99 latency | 114.98s | 22.53s |
| total tokens (10 claims) | 203,301 | 22,379 |
| cost per claim | $0.00354 | $0.00043 |

Multiplier: still **0.1x**. Dominant hand-off: still `facts_worker -> coverage_worker`, 61%.

**The fix worked, measurably.** C-001, C-002, and C-008 — three of the four claims §8.3
named specifically — are now exactly correct (`PAYABLE/7000`, `PAYABLE/12000`,
`PAYABLE/4000`, matching gold to the rupee). C-007 is still wrong, but for the *other*,
already-disclosed reason: the deductible resolves correctly to 1000 now (`40000 - 1000 =
39000`), but nothing computes the $6,000 hire-car exclusion, so the claimed amount going
into that subtraction is still the full $40,000 instead of gold's $34,000. That gap was
named in §5 before this fix and is still open — this run just makes it visible on its own,
no longer hidden behind the deductible bug.

Two claims that were previously right went wrong this run — **C-003** (now `PAYABLE/4900`
instead of the correct `NOT_PAYABLE`, missing the tyres-only exclusion) and **C-009** (now
`REFERRED` instead of `NOT_PAYABLE`, because the retrieved passages this run didn't happen
to include the mechanical-breakdown clause text). Both are the *same class* of miss §5
already named — an exclusion-recognition judgment call, not a deductible one — landing on
different claims than before. Nothing about `_resolve_deductible` touches exclusion
reasoning at all; this is run-to-run variance in the same known weak spot, not a
regression the fix caused.

### 9.3 A cosmetic gap found while checking this, disclosed rather than fixed

The corrected `deductible` number is what `compute_payout` uses, so `payable_amount` — the
number `grade()` actually checks — is correct on every claim above. But the coverage
worker's own `why` text is generated *before* `_resolve_deductible` overrides its number, so
the manager's synthesized rationale still says things like *"the compulsory deductible of
INR 1,500"* for C-001, C-002, C-007, and C-008 even though the real figure used was 1000 or
3000. The graded output is right; the sentence explaining it still cites the old, wrong
number. This wasn't part of what was asked (fix the tier-selection bug, not the narrative
text), so it's surfaced here rather than patched — a follow-up would thread the resolved
number back into `decision["why"]` (or regenerate it) before the manager ever sees it.

### 9.4 Current verdict

Updated once more in `verdict.md`. The gap narrowed for real — 40%→60% on a repeatable,
verifiable fix, not noise — but the team still loses to the single agent's 80%, and the two
remaining failure classes (C-007's missing partial-exclusion arithmetic, and the
exclusion-recognition misses that moved from C-009 to C-003/C-009 between runs) are neither
small nor already fixed.

---

## Bonus — AgentCard and the A2A task lifecycle

**The AgentCard** the orchestrator would advertise over A2A is in `agent_card.json` — one
skill (`triage-motor-claim`), no streaming, a `bearer` auth scheme named but not
implemented (the closest real analogue in this repo is Week 9's `gateway_server.py` token
scoping, built for MCP not A2A, but the same shape: a caller should not get an
undifferentiated credential).

**Mapping the failed case (§6) onto the A2A task lifecycle**: A2A's `input-required` state
is for when the *agent itself* needs more from the *human* to proceed — a missing claim
number, a fact only the adjuster has. That is not what happened here. The coverage worker's
backend was down; no adjuster confirmation would bring it back up. Marking this
`input-required` would be actively misleading: it tells a UI to wait on a human question
that was never asked, and the claim would stall forever waiting for an answer nobody is
going to give. The correct mapping is **`failed`** for the coverage-worker sub-task
specifically (a real dependency outage, disclosed as one) — while the parent orchestrator
task can still legitimately reach **`completed`**, carrying a REFERRED result that honestly
says why, exactly as `orchestrator.py` already does with `degraded`/`worker_error`. Failing
the sub-task and completing the parent with a labeled degradation is not a contradiction —
it's the same distinction react_agent.py's own REFERRED-on-budget-exhaustion fallback makes
between "the run stopped" and "the claim was, honestly, not decided."

**What A2A buys over a plain REST call to the worker, in two lines**: (1) a shared task
lifecycle and typed result shape — `submitted/working/input-required/completed/failed` and
an Artifact schema — instead of every team inventing its own status codes and JSON shape,
the same standardisation MCP gives tool calls; (2) the AgentCard itself is a discovery and
auth-negotiation contract a caller can read *before* calling, the same role `tools/list`
plays for MCP servers — a bare REST endpoint has neither, only whatever's in a wiki page
that can drift out of date.
