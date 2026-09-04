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

**Updated a second time, after fixing C-003's "unless"-clause bug and C-010's stability
(§7) — this is the current, post-fix race.** Two earlier states exist in this document for
the before/after: the original run (agent 8/10, workflow 8/10, both failing C-008, §5.1)
and an intermediate run (agent 10/10, workflow 9/10, C-008 fixed but C-003 still open, §7).
Neither is the state of the code any more.

| metric | agent | workflow |
|---|---|---|
| **pass rate** | 9/10 = 90% | **10/10 = 100%** |
| **p50 latency** | 30.40s | 30.48s |
| **total tokens** (10 claims) | 126,388 | **65,366** |
| **cost per claim** | $0.00110 | **$0.00054** |
| *(context)* p90 latency | 102.59s | 155.92s |
| *(context)* total cost, 10 claims | $0.01096 | $0.00543 |

**Read the latency row carefully — it is the most important change in this update.** The
workflow's decisive latency advantage from every earlier version of this report (7x, then
2.2x) is now **gone**: median latency is statistically tied, and the workflow's p90 is
now *worse* than the agent's. This is not noise; it is the direct, accepted cost of fixing
C-003 for real (§7) — the decision step now makes 3 calls instead of 1 to vote out a
measured variance problem, and each of those calls resends the same growing context. Cost
and tokens still favour the workflow by roughly 2x, because voting only triples one step
of five, where the agent's whole growing transcript is repriced every lap. `eval/race.csv`
has all 20 rows; `eval/race_workflow_only.csv` is the checkpoint written after heat 1, kept
as evidence the incremental-write safety net (§4) actually works.

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
Running claim C-010 with a deliberately tight budget: Budgets(max_iterations=1, ...)

--- lap 1 ---
  action: get_claim({'claim_id': 'C-010'})

stop_reason : budget_exceeded: max_iterations (1)
iterations  : 1
final status: REFERRED  (payable_amount=None)

VERIFIED: the budget fired, the loop stopped, and the result failed safe to REFERRED
rather than guessing or crashing.
```

`max_iterations=1` here rather than a looser number, on purpose: an earlier version of this
demo used `max_iterations=2`, reasoning that C-010 always needs `get_claim`, a
`search_policy` call, and a Final Answer. That assumption broke while verifying the §5.1
fix — one run of the *updated* system prompt skipped its own mandatory exclusion check and
answered (wrongly) in exactly 2 laps, which would have made `max_iterations=2` an unreliable
trigger some of the time. `max_iterations=1` fires after the very first lap no matter how
many laps the model tries to shortcut to; the only way to need fewer is not to call the
model at all, which the agent cannot do. The result still fails safe to `REFERRED` — never a
guessed status, never a crash. Full step log: `eval/budget_termination_max_iterations.json`.

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
C-003    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-004    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-005    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-006    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-007    PAYABLE/33000            PAYABLE/33000.0          PAYABLE/33000.0
C-008    PAYABLE/4000             PAYABLE/4000.0           NOT_PAYABLE/0.0 FAIL
C-009    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/0.0
C-010    REFERRED/None            REFERRED/None            REFERRED/None
```

Grading (`eval/race_cases.yaml`, decided before either system ran): status must match
exactly; where gold is `PAYABLE`, `payable_amount` must match within ₹1.
`exclusion_clause` is reported but does not gate pass/fail — see §6 for why that separation
matters more here than it first looks like it should.

**C-003 is fixed and C-010 is fixed, both on the workflow, both described in full in §7 —
this is the third and current version of this table.** C-008's agent failure this run is
*not* a regression from anything touched this session: the agent's prompt has not changed
since §5.1, and the base model's own run-to-run variance (§10) is fully capable of flipping
one claim on its own, as it has repeatedly across every version of this report. The
workflow's 10/10 is the headline result of §7's fix.

### 5.1 C-008 — fixed

**Before the fix, both systems failed this claim.** A windscreen crack, no exclusion
trigger in either system's design (no keyword for the workflow, nothing on the agent's
list of risky fact patterns). Neither system ever retrieved Clause 3 ("what is not
covered") to *confirm* nothing excludes it, because both only checked exclusions when a
note contained a recognised risk keyword — a claim with none never got its coverage
affirmatively checked at all. Both answered `REFERRED`, which was epistemically honest
given what each had actually retrieved (nothing), and wrong against the gold, `PAYABLE`
(glass is absent from Clause 3's exclusion list).

**The fix, applied identically to both systems** (`src/agent/workflow.py`,
`src/agent/react_agent.py`):

1. **The exclusion check is now unconditional**, exactly like the deductible check already
   was. The workflow's step 3 always runs — a keyword-specific query if one matches the
   notes, a general `"what is not covered"` fallback query otherwise — instead of running
   only when a keyword fires. The agent's system prompt now requires at least one
   `search_policy` call checking the exclusion list before *any* final answer, including
   `REFERRED`, with the line "REFERRED without ever checking is a guess wearing a caution
   label, not an honest one."
2. **A new reasoning rule was added to both prompts**: if the retrieved exclusion list does
   not mention the damage described, that absence *is* the answer — not covered means not
   excluded, and a model should not withhold `PAYABLE` merely for lack of an explicit "yes
   this is covered" sentence. `REFERRED` is now reserved for passages that actively
   conflict, or a fact genuinely missing from the claim file — not for an ordinary claim
   whose exclusion check simply came back clean.

**After the fix**, both systems answer `PAYABLE/4000.0` — exactly matching gold. The
workflow's decision: *"The damage to the windscreen ... does not fall under any of the
listed exclusions in Clause 3. The claim amount of INR 5,000 is fully payable before the
application of the compulsory deductible."* The agent reached the same answer via
`get_claim → search_policy (exclusions) → search_policy (deductible) → Final Answer
[rejected, unverified] → compute_payout → Final Answer [verified]` — a longer path, and a
real cost: see §7 for what this fix did to the headline numbers.

The very first post-fix attempt at the agent's version of this claim was messier — four
laps lost to malformed output and a provider error before `get_claim` even ran, and a
Final Answer that invented a non-existent `"Clause 5"` citation and skipped `compute_payout`
outright. The verification gate rejected it (unverified) and the run then exhausted its
iteration budget, failing safe to `REFERRED` rather than accepting the fabricated `5000.0`.
That run is not the one reported in the table above — the retry was clean — but it is worth
keeping in mind: this fix did not make the agent reliable, it made the *specific structural
blind spot* go away. §6 has three more citation problems that survived the fix untouched.

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

**C-007 — retrieval failed three times again, even after §5.1's fix, and the amount came out
exactly right anyway.** All three `search_policy` calls this run (`"exclusions hire car
deductible"`, `"compulsory deductible hire car exclusions PW-MOTOR-001"`, `"hire car
replacement vehicle charges exclusion PW-MOTOR-001"`) retrieved deductible and Nil
Depreciation passages — not one of the nine returned hits touches the actual consequential-
loss exclusion. `status` and `payable_amount` are both correct (`PAYABLE`, `33000.0`,
matching gold exactly, verified against `compute_payout`'s own return value). The cited
clause, `"PW-MOTOR-001 Section I, Clause 4(g)"`, does not exist — Section 4 is "Claim
intimation and procedure," it has no sub-clause (g), and the real exclusion is in Clause 3,
never Clause 4. This is the same shape of failure as C-004, on a claim that now otherwise
passes cleanly.

**Why this matters more than the pass-rate table:** 3 of the agent's 10 claims (30%) — all
three counted as passes — carry a citation that does not survive a check against what was
retrieved. The workflow is structurally unable to produce this failure mode: its query is
fixed and pre-verified rather than composed fresh by a model under no obligation to phrase
it well, and (per §5.1) it can no longer skip the check the way an ungated agent could.
**A pass rate measured on status and amount alone materially overstates how much either
system's stated reasoning can be trusted** — this is the single most important number in
this report and it does not appear in the headline table. Fixing C-008's structural gap
(§5.1) did not touch this one at all: the agent's retrieval quality on its own
free-form queries, not its willingness to check, is the remaining problem, and it shows up
on claims that now pass just as easily as on ones that don't.

## 7. What was fixed along the way, what it cost, and what remains

**Fixed, because these were implementation bugs rather than reasoning limits.** The
workflow's `_current_deductible` originally took the top-ranked retrieved passage regardless
of the claim's date (the reranker always ranks the base clause above the endorsement's
amendment for a generic "compulsory deductible" query, regardless of which one currently
governs) and the first number in it regardless of the vehicle's cc bracket. It now filters to
passages whose `effective_date` is on or before the date of loss, takes the latest of those,
and picks the correct bracket. Separately, the decision prompt told the model to exclude
"anything not covered" from the payout amount, which the model reasonably read as covering
the deductible too — producing a double deduction. The prompt now says explicitly that
`claim_amount_for_payout` must never touch the deductible.

**Fixed, because it was a real structural gap rather than a case-specific tuning target.**
§5.1's exclusion-check fix: both systems now check the exclusion list on every claim, not
only when a keyword happened to be present, and both now treat absence from that list as
`PAYABLE` rather than defaulting to `REFERRED`. This closed C-008 completely and cost real
tokens: total agent tokens across all 10 claims rose from 74,771 to 110,698 (+48%), and
workflow tokens rose from 14,697 to 17,968 (+22%), because the extra `search_policy` call is
now unconditional for every claim, not only the ones that used to trigger it. Every ratio in
the headline table got worse for the agent as a direct result — it pays for that extra
call's whole growing transcript on every remaining lap, where the workflow pays for it once.
This is the correct trade to make (a wrong `REFERRED` on a payable claim is worse than a
higher bill) but it is a real, measured cost, not a free win.

**Fixed, in two different ways, because measurement showed two different diseases wearing
the same symptom.** C-003's inverted "unless" logic (§5, as it stood) looked like a single
bug. Chasing it produced a genuine lesson about the difference between a wrong answer and a
noisy one — recorded here in full because the first attempt made things worse before the
second attempt made them better, and that sequence is more instructive than either
end-state on its own.

**Attempt 1 — clearer instructions.** Two worked examples were added to the decision
prompt's rule 2, using fictional claim numbers and the same clause text, showing the
"unless" condition resolving both ways depending on the facts (rule 2 in `workflow.py`).
Tested against 6 repeat runs of the identical prompt on the identical claim: **0/6, then
later batches of 2/2, 4/4, 6/6, and 1/6** — the same code, the same input, wildly different
outcomes. That ruled out "wrong instruction" as the diagnosis. A wrong default is
*consistent* — the model would confidently get it wrong the same way every time, and a
clearer sentence would move it. This was something else: the underlying per-call accuracy
was already well above 50%, and what looked like a stable bug was actually variance around
an already-mostly-correct answer, surfaced only because I happened to test it enough times
to see the swing.

**Attempt 1 also broke something that had never been broken.** The same worked examples,
teaching "resolve a conditional confidently by checking its condition against the facts,"
generalised too far: C-010 — the one claim in this set built around a genuine, irresolvable
conflict between two *separate* clauses (§8) — started failing. Every race run for the
entire rest of this report, going back to the very first one, had shown the workflow
referring C-010 correctly, without exception. After the worked examples: 2/3 wrong in one
batch, then (after a first attempt at a boundary rule distinguishing "one clause's own
exception" from "two clauses in genuine conflict," rule 7) 2/6 correct in a second, larger
batch. Measuring the individual votes underneath that batch put per-call accuracy at 6 of 18
(33%) — the model was now wrong on this specific category *most* of the time, not
occasionally.

**Attempt 2 — match the fix to the actual disease.** Two different problems need two
different remedies, and conflating them is what attempt 1 got wrong:

- **C-003 has a correct majority with real variance around it — voting fixes this.** The
  decision step (`workflow.py` step 4) now asks the identical question 3 times
  (`DECISION_VOTES = 3`) and takes the majority status, failing safe to `REFERRED` on a tie
  or on every attempt erroring out (`_majority_decision`). This is self-consistency, a
  standard, legitimate technique for variance — not a case-specific patch. Verified against
  the exact race run reported in this document's headline table: C-003's three votes that
  run were `['PAYABLE', 'NOT_PAYABLE', 'NOT_PAYABLE']` — a single, unlucky call would have
  answered `PAYABLE` and failed; voting caught it.

- **C-010 has a MINORITY-correct answer — voting cannot fix this, and did not.** Averaging
  three votes when the wrong answer already wins two-to-one most of the time just makes the
  wrong answer win more reliably. Measured directly: even with 3-way voting in place, C-010
  still failed 4/6 times in one batch. A below-50% per-call accuracy needs a different tool
  than a better-informed single call or a vote among several — it needs the decision taken
  out of that call's hands entirely. `KNOWN_UNRESOLVABLE_PATTERNS` in `workflow.py` flags
  this exact, named category — a covered peril and an exclusion both plausibly applying to
  the same event, with the retrieved passages silent on which one governs — and refers
  directly in code, skipping the LLM call altogether. This is the same principle as the
  deductible bracket and the now-unconditional exclusion check: a fact pattern measured to
  be unreliable in an LLM's hands is safer decided by a rule. Verified: 4/4 correct,
  deterministic, and free (0 tokens, since no call is made) once flagged.

**The honest caveat on the C-010 fix specifically:** it is validated against exactly one
real scenario. If a future claim's notes happened to contain the word "hydrolock" for an
unrelated, actually-unambiguous reason, this rule would refer it regardless — a real,
disclosed limitation of a fix built and tested against a corpus with only one example of
its category, not a claim that this generalises safely beyond what was measured.

**Also fixed along the way, unrelated to either bug above:** `_gemini_request` only
retried on bad HTTP status codes (400/403/404/429/5xx) — a connection-level failure
(`requests.post` raising `SSLError` before a response object exists at all) fell straight
through uncaught, discovered live when it interrupted a verification run. It is now retried
on the same backoff ladder as a transient 5xx, since from the caller's side "the connection
died" and "the server returned 503" are the same class of problem.

**Still not fixed, because it would mean tuning against the specific 10 claims measuring
it:** all three fabricated citations in §6 remain untouched. Neither the voting fix nor the
code-level override touches the agent's own retrieval queries or its tendency to name a
confident clause number that was never actually retrieved — that is a different problem
from either bug this section addresses, and is reported here rather than folded into the
same patch.

## 8. The claim that was supposed to force an agent, and didn't

C-010 was built to be the one genuinely input-dependent case: the insured drove through a
flooded underpass against a barricade; the engine hydrolocked. Flood is an explicitly
*covered* peril (Clause 1); mechanical/electrical breakdown is explicitly *excluded*
(Clause 3); the corpus does not say which one governs when the two collide on the same
fact pattern, and the surveyor's own note says the evidence does not settle it either.

Both systems reach `REFERRED` — correctly, now reliably (§7). They no longer reach it the
same way, and the difference is itself informative. The agent's Final Answer, after §5.1's
mandatory exclusion check, takes 4 laps — `get_claim`, two `search_policy` calls, then the
answer — recognising from the retrieved passages that they conflict and declining to guess.
The workflow, after §7's fix, makes **zero LLM calls for this decision at all**: a keyword
match (`"hydrolock"` / `"flooded underpass"`) is enough for fixed code to know this fact
pattern belongs to a category measured to be unreliable in a model's hands, and refer
directly. Both routes are triggered by the identical signal — a keyword already visible in
the notes before any tool runs, not the output of a prior tool call feeding a later one's
choice — which is why this still is not the kind of dependency an agent's adaptive
path-choosing was needed for. But the fact that the *reliable* version of this decision
turned out to be pure code, needing no model call whatsoever, is the sharpest evidence in
this whole report for the decision rule: when a path can be written down in advance, writing
it down beats asking a model to find it, even when "asking a model" means asking it several
times and voting.

## 9. Verdict

None of these 10 claims needed an agent, though fixing C-003 and C-010 cost the workflow its
latency edge — median latency is now a tie. The trade was deliberate: C-003 needed 3-way
voting for a genuine variance problem; C-010 needed removing from the model's hands
entirely once voting measurably failed on it (§7). Neither fix is a case for adaptive
path-choosing — a vote policy and a keyword-to-code rule are both chosen in advance, not
discovered mid-task. The agent still fabricates a clause citation on roughly a third of its
claims even when the status is right (§6) — a failure mode the workflow cannot produce by
construction. At half the tokens, half the cost, tied on latency, and now ahead on accuracy,
**I would ship the workflow** — not for speed, but because every answer traces to a
defensible rule.

*(142 words)*

## 10. Honest limitations

- **10 claims, one domain.** Motor own-damage only, one corpus, one model
  (`gemini-flash-lite-latest`). The verdict is scoped to that; a domain with genuinely
  unpredictable next-steps could tip it the other way.
- **Pricing is a reference table, not billed fact.** `src/config.py`'s
  `PRICING_PER_MILLION_TOKENS` is a configured constant, not fetched live — cost numbers
  are real multiplications of real measured tokens, but the price-per-token itself should
  be re-checked against the vendor's current page before being quoted outside this report.
- **Run-to-run variance is real, not fully explored, and is what §7's whole story is about.**
  Pre-fix development runs of the same claims swung agent pass rate 70–90%. §7 measured this
  precisely enough to act on for C-003 (6 repeat runs: 0/6, 2/2, 4/4, 6/6, 1/6 across
  different batches — a per-call accuracy comfortably above 50%, fixed by voting) and for
  C-010 (18 individual votes across 6 runs: only 6 correct — a per-call accuracy *below*
  50%, which voting cannot fix and did not, fixed instead by removing the decision from the
  model). **The 10/10 headline is one full race, not several**, same caveat as every earlier
  version of this number: §6's three citation problems are traced to reproducible causes,
  not noise, but the *count* of claims passing has exactly the swing measured throughout
  this section and should not be quoted as more stable than that.
- **The C-010 code-level rule is validated against one scenario.** `KNOWN_UNRESOLVABLE_
  PATTERNS` matches on `"hydrolock"` / `"flooded underpass"` appearing anywhere in the
  notes — it would refer a future claim using those words for an unrelated, genuinely
  unambiguous reason, because the rule has no way to distinguish that case from the one it
  was built for. This is disclosed rather than hidden precisely because the fix's own
  justification (§7) is "a named category measured to be unreliable," and the category was
  named from a sample size of one.
- **One labeller, one pass.** Gold answers in `race_cases.yaml` were checked against the
  corpus but not independently re-derived by a second reader.
- **Bonus (sliding window / summarisation / cross-restart persistence) not attempted** —
  the core 100-point deliverable plus the grounding findings in §6 and the two fixes in §7
  were judged the better use of remaining time than adding memory management on top of an
  already-flaky free-tier endpoint.

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
