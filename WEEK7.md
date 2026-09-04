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

**Updated after fixing the C-008 gap (§5.1) — this is the current, post-fix race.** The
original run (agent 8/10, workflow 8/10, both failing C-008) is kept in §5.1 for the
before/after; it is no longer the state of the code.

| metric | agent | workflow |
|---|---|---|
| **pass rate** | **10/10 = 100%** | 9/10 = 90% |
| **p50 latency** | 13.89s | **6.35s** |
| **total tokens** (10 claims) | 110,698 | **17,968** |
| **cost per claim** | $0.00097 | **$0.00015** |
| *(context)* p90 latency | 58.52s | 12.83s |
| *(context)* total cost, 10 claims | $0.00974 | $0.00154 |

The workflow still wins decisively on latency (2.2x), tokens (6.2x) and cost (6.3x) — all
three ratios got *worse* for the agent after the fix, because the fix made an extra tool
call mandatory on every claim, and the agent pays for that call's entire growing transcript
every lap while the workflow pays for it once. But accuracy is no longer tied: the agent is
now 10/10 against the workflow's 9/10. §7 explains precisely why, and why that is not
evidence an agent was needed for any of these claims. `eval/race.csv` has all 20 rows;
`eval/race_workflow_only.csv` is the checkpoint written after heat 1, kept as evidence the
incremental-write safety net (§4) actually works.

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
C-003    NOT_PAYABLE/0            PAYABLE/1700.0  FAIL     NOT_PAYABLE/0.0
C-004    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-005    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-006    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/None
C-007    PAYABLE/33000            PAYABLE/33000.0          PAYABLE/33000.0
C-008    PAYABLE/4000             PAYABLE/4000.0           PAYABLE/4000.0
C-009    NOT_PAYABLE/0            NOT_PAYABLE/0.0          NOT_PAYABLE/0.0
C-010    REFERRED/None            REFERRED/None            REFERRED/None
```

Grading (`eval/race_cases.yaml`, decided before either system ran): status must match
exactly; where gold is `PAYABLE`, `payable_amount` must match within ₹1.
`exclusion_clause` is reported but does not gate pass/fail — see §6 for why that separation
matters more here than it first looks like it should.

**C-003 (workflow still fails) — a real reading-comprehension slip, not a code bug, and left
unfixed on purpose.** Only the tyres were damaged. Clause 3: *"damage to tyres and tubes
UNLESS the vehicle is damaged at the same time, in which case liability is limited to
50%."* The retrieved passage was exactly right (`PW-MOTOR-001 Section 3`, correctly cited).
The workflow's own rationale states *"no other part of the vehicle was damaged"* —
correctly recognising the exception's precondition is false — and then applies the
50%-liability exception anyway, inverting its own stated logic. One clarifying rule was
added to both prompts afterward ("check Y against the claim before applying any exception
inside an exclusion") because the error is generalisable, not case-specific; it did not
eliminate this instance, and I stopped there rather than keep tuning against 10 fixed cases
(see §7). **This is currently the single thing standing between the workflow and 10/10** —
worth knowing precisely, since it is a small, well-diagnosed gap, not a deep one.

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

**Not fixed, because it would mean tuning a prompt against the specific 10 claims being used
to measure it** — the exact anti-pattern Week 6 flagged when relabelling disagreements to
inflate an agreement score. C-003's inverted "unless" logic remains (§5), and all three
fabricated citations in §6 remain untouched: the exclusion-check fix made both systems
*check*, it did not make the agent's own retrieval queries any better at *finding* the right
passage once it decided to look, and it did not stop the model from confidently naming a
clause number that was never actually retrieved. Those are separate problems from the one
this task asked me to fix, reported honestly rather than folded into the same patch.

## 8. The claim that was supposed to force an agent, and didn't

C-010 was built to be the one genuinely input-dependent case: the insured drove through a
flooded underpass against a barricade; the engine hydrolocked. Flood is an explicitly
*covered* peril (Clause 1); mechanical/electrical breakdown is explicitly *excluded*
(Clause 3); the corpus does not say which one governs when the two collide on the same
fact pattern, and the surveyor's own note says the evidence does not settle it either.

Both systems reached `REFERRED` — correctly. Both reached it by the same mechanism: a
keyword match (`"hydrolock"` / `"flooded underpass"`) retrieved the conflicting clauses, and
one LLM decision (the workflow's single call; the agent's Final Answer, now taking 4 laps
after §5.1's fix — `get_claim`, two `search_policy` calls, then the answer, since checking
the exclusion list is mandatory whether or not it changes the outcome) recognised the
passages conflict and declined to guess. Nothing about this claim needed *iteration* in the
sense that matters for the decision-rule question — no step's tool CHOICE depended on
reading another tool's OUTPUT, only on a keyword already visible in the notes before any
tool ran. The extra laps §5.1 added are a fixed cost paid on every claim, C-010 included, not
evidence of adaptive reasoning this claim required. The dependency this claim was designed
to force turned out to be answerable by one shot, same as every other claim in the set.

## 9. Verdict

None of these 10 claims needed an agent — even post-fix, when the agent scored 10/10 against
the workflow's 9/10. That gap traces to an ordinary reading-comprehension bug in the
workflow's one decision call (C-003, §5), not to any claim needing adaptive path-choosing a
fixed pipeline structurally cannot do; the same bug could be fixed the same way in either
architecture. Every dependency here — deductible-by-date, exclusion-by-keyword, C-010's
conflict — was resolved by a fixed lookup table plus one LLM call. Meanwhile the agent,
despite the higher score, fabricated a clause citation on 3 of its 10 claims, including two
it otherwise got right (§6) — a failure mode the workflow cannot produce by construction. At
2x the latency, 6x the tokens and 6x the cost, **I would still ship the workflow**, fix
C-003's specific bug directly, and treat the agent's citations as reason for more scrutiny,
not less.

*(149 words)*

## 10. Honest limitations

- **10 claims, one domain.** Motor own-damage only, one corpus, one model
  (`gemini-flash-lite-latest`). The verdict is scoped to that; a domain with genuinely
  unpredictable next-steps could tip it the other way.
- **Pricing is a reference table, not billed fact.** `src/config.py`'s
  `PRICING_PER_MILLION_TOKENS` is a configured constant, not fetched live — cost numbers
  are real multiplications of real measured tokens, but the price-per-token itself should
  be re-checked against the vendor's current page before being quoted outside this report.
- **Run-to-run variance is real, not fully explored, and applies to the post-fix numbers
  too.** Three pre-fix development runs of the same claims swung agent pass rate 70–90%.
  The fix itself was verified on C-008 alone across two attempts: the first burned four laps
  on malformed output and a provider error, invented a citation to a non-existent
  `"Clause 5"`, and was correctly rejected by the verification gate down to a safe
  `REFERRED`; the retry succeeded cleanly in 6 laps. **The 10/10 headline in §0 is one full
  race, not several** — §5-6's specific diagnoses (a skipped tool call, a genuinely misread
  clause, a citation that outruns retrieval) are traced to reproducible causes, not noise,
  but the *count* — 10/10 rather than 9/10 or 8/10 on a re-run — has exactly the swing this
  bullet describes, and should not be quoted as more stable than it has been shown to be.
  The Week-6 lesson applies here too: don't trust a single number smaller than the run-to-run
  swing already measured.
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
