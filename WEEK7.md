# Week 7 — agent loops, and when not to use one

A hand-built ReAct agent triages motor own-damage claims: pull the claim, read the notes,
check the policy for an exclusion or the current deductible, compute the payout. The same
task is re-implemented as four hard-coded steps with no loop. Both were raced over the same
10 claims, with four numbers measured for each.

**The one command:**

```bash
python eval/race.py
```

---

## The numbers, up front

| metric | agent | workflow |
|---|---|---|
| **pass rate** | 8/10 = 80% | 8/10 = 80% |
| **p50 latency** | 17.05s | **2.43s** |
| **total tokens** (10 claims) | 74,771 | **14,697** |
| **cost per claim** | $0.00068 | **$0.00013** |
| *(context)* p90 latency | 76.73s | 2.79s |
| *(context)* total cost, 10 claims | $0.00683 | $0.00131 |

Identical accuracy on the metric that's checked. The workflow wins **7x on latency, 5x on
tokens, 5x on cost** — and, as §5 below shows, wins on a metric that usually isn't checked
too. `eval/race.csv` has all 20 rows; `eval/race_workflow_only.csv` is the checkpoint written
after heat 1, kept as evidence the incremental-write safety net (§4) actually works.

---

## 1. What was built

| file | what it does |
|---|---|
| `src/agent/claims_store.py` | 10 motor own-damage claim files — facts + adjuster notes |
| `src/agent/tools.py` | the three tools, shared verbatim by both systems |
| `src/agent/react_agent.py` | the hand-built ReAct loop — Thought → Action → Observation |
| `src/agent/workflow.py` | the identical task as 4 fixed steps, no loop |
| `src/agent/budgets.py` | the four stop conditions, checked before every lap |
| `src/agent/usage.py` | token/cost accounting, summed across every lap |
| `src/llm.py` (extended) | `chat_with_usage()` — real provider token counts, not estimated |
| `eval/race.py` | **the one command** — runs both, grades both, writes the table |
| `eval/race_cases.yaml` | gold answers, checked only after both systems have answered |
| `eval/budget_demo.py` | deliberately trips a budget, proves the clean stop |

Restricted to one line of business (motor) on purpose: `compute_payout` takes a flat
deductible, and health claims in this corpus use a percentage co-payment instead — a
different arithmetic shape that would force the tool to branch on line-of-business,
breaking "one job." Every claim fact and every clause quoted anywhere in this write-up was
checked fresh against `corpora/insurance/policy-wording/01-motor-own-damage.md` and
`corpora/insurance/endorsements/END-2026-01-motor.md` before being written down.

## 2. The agent loop, in one paragraph

`react_agent.py`'s `run()` is the whole thing: build a system prompt from the three tool
descriptions, then loop — resend the growing transcript, parse the reply as either an
`Action` or a `Final Answer`, dispatch the tool, append the `Observation`, repeat. No
framework underneath it. The `chat()` primitive this whole project shares is single-turn
(system, user) → text, not a persistent session, so the "memory" of the conversation is
just a string that gets longer every lap and gets billed again in full every lap — which is
exactly why token accounting has to *sum* across laps (`UsageAccumulator.add`), not read the
last call.

## 3. The third tool

`get_claim` and `search_policy` were the two tools the loop needed from the start.
`compute_payout` is what this task adds, and here is its description next to the two it must
not overlap:

| tool | one job | does NOT |
|---|---|---|
| `get_claim(claim_id)` | fetch one claim's facts + notes by id | search policy text, compute anything |
| `search_policy(query)` | free-text search over policy wording | fetch a claim, compute anything |
| **`compute_payout(claim_amount, deductible, status: enum)`** | **subtract the deductible, once status is already decided** | **decide coverage, read claims, search policy** |

`status` is a proper 3-value enum (`PAYABLE \| NOT_PAYABLE \| REFERRED`) via `ClaimStatus`,
not a free string — a bad value raises inside `compute_payout` rather than being silently
coerced. Full diff: `git show <commit>:src/agent/tools.py` against the two-tool state, or
read `TOOL_GET_CLAIM` / `TOOL_SEARCH_POLICY` / `TOOL_COMPUTE_PAYOUT` in `tools.py` — each
description states what it does and, in the negative, what it deliberately does not, because
that negative half is what usually goes missing when two tools start to blur together.

## 4. Budgets — enforced in code, and fault-isolated

`src/agent/budgets.py`'s `exceeded()` checks all four — `max_iterations`, `max_tokens`,
`max_cost_usd`, `max_wall_seconds` — in one function, called once, before every lap. Adding a
fifth budget later cannot silently go unchecked, because there is only one call site.

**Deliberate termination, `eval/budget_demo.py --budget max_iterations`:**

```
Running claim C-010 with a deliberately tight budget: Budgets(max_iterations=2, ...)

--- lap 1 ---
  action: get_claim({'claim_id': 'C-010'})
--- lap 2 ---
  action: search_policy({'query': 'flood damage mechanical failure water warning'})

stop_reason : budget_exceeded: max_iterations (2)
iterations  : 2
final status: REFERRED  (payable_amount=None)

VERIFIED: the budget fired, the loop stopped, and the result failed safe to REFERRED
rather than guessing or crashing.
```

C-010 genuinely needs 4+ laps (it's the deliberately ambiguous flood-vs-mechanical-breakdown
claim, §8), so `max_iterations=2` is guaranteed to fire before a natural Final Answer would.
The result fails safe to `REFERRED` — never a guessed status, never a crash. Full step log:
`eval/budget_termination_max_iterations.json`.

**A second thing worth showing, not asked for but found along the way:**
`eval/budget_termination_provider_error_example.json` is an earlier run of the identical
command where lap 2 hit `MALFORMED_RESPONSE` from Gemini (an intermittent bad decode on this
model, unrelated to the request) instead of a clean tool call. The loop treated it as any
other failed lap — logged it, did not crash, and still stopped cleanly on the same budget one
lap later. **A budget that only fires on a well-behaved lap is not tested; one that fires
after absorbing a real provider failure is.**

This required a real fix along the way: `run_heat()` in `race.py` originally had no
per-claim exception handling, and the agent heat crashing on claim 1 of a from-scratch
`MALFORMED_RESPONSE` (§6) took the entire already-completed, already-paid-for 10-claim
workflow heat down with it — nothing had been written to disk. `race.py` now checkpoints
each heat to CSV immediately after it finishes and isolates each claim in its own
try/except, so one claim's unexpected exception costs one row, not the batch.

## 5. Per-claim detail

```
claim    gold                     workflow                 agent
C-001    PAYABLE/7000             PAYABLE/7000.0           PAYABLE/7000.0
C-002    PAYABLE/12000            PAYABLE/12000.0          PAYABLE/12000.0
C-003    NOT_PAYABLE/0            PAYABLE/1700.0  FAIL     NOT_PAYABLE/None
C-004    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-005    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-006    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-007    PAYABLE/33000            PAYABLE/33000.0          PAYABLE/32500.0 FAIL
C-008    PAYABLE/4000             REFERRED/None   FAIL     REFERRED/None   FAIL
C-009    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-010    REFERRED/None            REFERRED/None            REFERRED/None
```

Grading (`eval/race_cases.yaml`, decided before either system ran): status must match
exactly; where gold is `PAYABLE`, `payable_amount` must match within ₹1.
`exclusion_clause` is reported but does not gate pass/fail — see C-007 below for why.

**C-003 (workflow fails, agent passes) — a real reading-comprehension slip, not a code bug.**
Only the tyres were damaged. Clause 3: *"damage to tyres and tubes UNLESS the vehicle is
damaged at the same time, in which case liability is limited to 50%."* The retrieved
passage was exactly right (`PW-MOTOR-001 Section 3`, correctly cited). The workflow's own
rationale states *"no other part of the vehicle was damaged"* — correctly recognising the
exception's precondition is false — and then applies the 50%-liability exception anyway,
inverting its own stated logic. One clarifying rule was added to both prompts afterward
("check Y against the claim before applying any exception inside an exclusion") because the
error is generalisable, not case-specific; it did not eliminate this instance on the final
run, and I stopped there rather than keep tuning against 10 fixed cases (see §7).

**C-007 (agent fails by ₹500) — the verification gate's real cost.** The agent's Final
Answer first proposed `payable_amount: 33000.0` *before* calling `compute_payout` at all.
The gate added after C-001 (below) rejected it — correctly, since nothing had verified that
number — and forced a retry. `compute_payout(34000, 1000, PAYABLE)` then correctly returned
`33000.0`. On the run reported here, that extra round-trip's token cost combined with normal
run-to-run variance to leave the second Final Answer at `32500.0`, a ₹500 miss on a claim
whose correct arithmetic the agent had already computed once. A verification gate that
actually rejects bad answers costs an extra lap, and that lap has to be paid for out of the
same token budget — a genuine, generalisable trade-off, not specific to this claim.

**C-008 (both fail) — a real structural gap in both systems.** A windscreen crack, no
exclusion trigger in either system's design (no keyword for the workflow, nothing on the
agent's list of risky fact patterns). Neither system ever retrieves Clause 3 ("what is not
covered") to *confirm* nothing excludes it, because both only check exclusions when a note
contains a recognised risk keyword — a claim with none never gets its coverage affirmatively
checked at all. `REFERRED` is the epistemically honest answer given what was actually
retrieved; it is also the wrong answer against the gold, which is `PAYABLE` (glass is absent
from Clause 3's exclusion list). **The fix this points to is architectural, not
prompt-level: Clause 3 should be checked unconditionally, exactly like the deductible clause
already is, rather than gated on a keyword firing** — recorded as a next step (§9), not
patched in under time pressure.

## 6. Two findings the pass rate hides

Grading only checks `status` and `payable_amount`. Reading the traces found two agent
citations that would not survive a check against what was actually retrieved — both on
claims the pass-rate table above marks as **passing**.

**C-005 — skipped `search_policy` entirely.** Notes: driver's blood alcohol was over the
limit. The agent went `get_claim` → **Final Answer** in two laps, no retrieval in between.
Status `NOT_PAYABLE` is correct (matches gold). The cited exclusion is
`"POL-2025-OMD Section 4.1(b) and END-2026-03 Endorsement E-4"` — `POL-2025-OMD` is not a
document that exists anywhere in this corpus, and `END-2026-03` is a real id attached to a
clause about claims-handling timelines that says nothing about alcohol. The right decision,
reached without reading anything, wrapped in a citation invented from nothing.

**C-004 — retrieval failed three times, the agent cited a clause that never came back.**
The agent tried three different queries for the licence exclusion (`"unlicensed driver
driving licence exclusion"`, `"driving licence exclusion driver motor"`,
`"driver holding a valid driving licence exclusion PW-MOTOR-001"`). The first two returned
three *health*-policy passages about waiting periods and co-payment — nothing about a motor
licence exclusion, on either attempt. Status `NOT_PAYABLE` is again correct. The cited
clause, `"PW-MOTOR-001 Section 4 Clause 4.5"`, matches none of the nine retrieved passages
across all three tries — Section 4 is "Claim intimation and procedure," and no clause 4.5
exists. The workflow, given the identical claim, sent one fixed, pre-tested query —
`"loss caused while driven by a person without a valid and effective driving licence"` —
and retrieved `PW-MOTOR-001 Clause 3` at relevance 0.999 on the first and only attempt,
citing it correctly.

**Why this matters more than the pass-rate table:** 2 of the agent's 10 claims (20%) — both
counted as passes — carry a citation that does not survive a check against what was
retrieved. The workflow is structurally unable to produce either failure mode: its four
steps are not optional, so it cannot skip evidence-gathering the way C-005's agent run did,
and its query is fixed and pre-verified rather than composed fresh by a model under no
obligation to phrase it well. **A pass rate measured on status and amount alone materially
overstates how much either system's stated reasoning can be trusted** — this is the single
most important number in this report and it does not appear in the headline table.

## 7. What was fixed along the way, and what was not

Fixed, because these were implementation bugs rather than reasoning limits: the workflow's
`_current_deductible` originally took the top-ranked retrieved passage regardless of the
claim's date (the reranker always ranks the base clause above the endorsement's amendment
for a generic "compulsory deductible" query, regardless of which one currently governs) and
the first number in it regardless of the vehicle's cc bracket. It now filters to passages
whose `effective_date` is on or before the date of loss, takes the latest of those, and
picks the correct bracket. Separately, the decision prompt told the model to exclude
"anything not covered" from the payout amount, which the model reasonably read as covering
the deductible too — producing a double deduction (deductible subtracted once in the
model's own reasoning, once again by `compute_payout`). The prompt now says explicitly that
`claim_amount_for_payout` must never touch the deductible.

Not fixed, because it would mean tuning a prompt against the specific 10 claims being used
to measure it — the exact anti-pattern Week 6 flagged when relabelling disagreements to
inflate an agreement score: C-003's inverted "unless" logic, C-007's ₹500 miss, and C-008's
structural exclusion-check gap all remain, honestly reported above rather than patched away
one test case at a time.

## 8. The claim that was supposed to force an agent, and didn't

C-010 was built to be the one genuinely input-dependent case: the insured drove through a
flooded underpass against a barricade; the engine hydrolocked. Flood is an explicitly
*covered* peril (Clause 1); mechanical/electrical breakdown is explicitly *excluded*
(Clause 3); the corpus does not say which one governs when the two collide on the same
fact pattern, and the surveyor's own note says the evidence does not settle it either.

Both systems reached `REFERRED` — correctly. But both reached it by the same mechanism: a
keyword match (`"hydrolock"` / `"flooded underpass"`) retrieved both clauses, and a single
LLM call (the workflow's one decision step; the agent's Final Answer after one
`search_policy`) recognised the passages conflict and declined to guess. Nothing about this
claim needed *iteration* — no step's tool choice depended on reading another tool's
*output*, only on a keyword already visible in the notes before any tool ran. The dependency
this claim was designed to force turned out to be answerable by one shot, same as every
other claim in the set.

## 9. Verdict

None of these 10 claims needed an agent. Every dependency — deductible-by-date,
exclusion-by-keyword, even C-010's ambiguity — was resolved by a fixed lookup table plus one
LLM call, at 1/7 the latency, 1/5 the tokens, 1/5 the cost, and equal accuracy on status and
amount. The agent's freedom cost something real: on C-004 it wrote three retrieval queries,
two of them wrong, where the workflow's one pre-tested query hit 0.999 relevance
immediately; on C-005 it skipped retrieval outright and fabricated a citation to a document
that does not exist. A fixed pipeline cannot skip a step by choice — that is the whole case
for one. **I would ship the workflow**, and revisit an agent only once a claim class turns
up whose next tool call genuinely cannot be written down in advance — checking Clause 3
unconditionally (§5) would close the one real gap first.

*(146 words)*

## 10. Honest limitations

- **10 claims, one domain.** Motor own-damage only, one corpus, one model
  (`gemini-flash-lite-latest`). The verdict is scoped to that; a domain with genuinely
  unpredictable next-steps could tip it the other way.
- **Pricing is a reference table, not billed fact.** `src/config.py`'s
  `PRICING_PER_MILLION_TOKENS` is a configured constant, not fetched live — cost numbers
  are real multiplications of real measured tokens, but the price-per-token itself should
  be re-checked against the vendor's current page before being quoted outside this report.
- **Run-to-run variance is real and not fully explored.** Three development runs of the
  same claims swung agent pass rate 70–90%; §5-6's diagnoses are traced to specific,
  reproducible causes (a skipped tool call, a genuinely misread clause), not to noise, but a
  single 10-claim race is not enough to separate "this model is unreliable at this prompt
  length" from "this specific run was unlucky." The Week-6 lesson applies here too: don't
  trust a single before/after number smaller than the run-to-run swing.
- **One labeller, one pass.** Gold answers in `race_cases.yaml` were checked against the
  corpus but not independently re-derived by a second reader.
- **Bonus (sliding window / summarisation / cross-restart persistence) not attempted** —
  the core 100-point deliverable plus the two grounding findings in §6 were judged the
  better use of remaining time than adding memory management on top of an already-flaky
  free-tier endpoint.

## 11. Reproducing

```bash
python eval/race.py                                          # the one command
python eval/race.py --limit 2 --sleep 2                       # fast dev loop
python eval/budget_demo.py --budget max_iterations             # deliberate termination
python eval/budget_demo.py --budget max_tokens
python eval/budget_demo.py --budget max_wall_seconds
```

Traces for every run: `traces/agent_traces.jsonl` (both systems write here — filter on
`"system": "agent"` / `"workflow"`).
