# Failure taxonomy — integrated system (Week 12)

**Sample:** census of 108 runs — the 36 eval claims on the first integrated run (`triage-v1`), the second (`triage-v2`) and the
**final system (`triage-v3` + structured chunking + exclusions gate + parser fix, "v3b")**. **Read:** by hand, one observation sentence per
run, before counting (`taxonomy_w12_notes.md`, verbatim; the v3b section is less blind than the first two — see its caveat).
**Counted by:** `eval/taxonomy_w12.py` (modes mechanical from saved data; R2 and R7 hand-coded). One reader — me — so not independent.

**Primary mode** = the one an adjuster would feel most, by the priority R4 > R1 > R6 > R7 > R2 > R5 > R3 > R8, so each run is counted once and the
column sums to 36. **Affected** counts every occurrence and overlaps.

| # | Failure mode | New from integration? | Affected v1 → v2 → **v3b** | Primary v1 → v2 → **v3b** | Severity | Example trace |
|---|---|---|---|---|---|---|
| R4 | **Empty packet** — the loop runs out of tokens, no Final Answer, nothing cited; a forced referral still reaches the adjuster | no (agent loop × budgets) | 5 → 2 → **6** | 5 → 2 → **6** | Annoys — nothing false is stated, the work is not done | `cap_7a5dfb3ca177` (v1 00468), `cap_045513f9f157` (v3b same claim) |
| R1 | **Superseded clause cited next to its replacement** — two conflicting figures in one packet | no (Week 6 version blindness) | 8 → 0 → **2** | 8 → 0 → **2** | **Wrongly pays** | `cap_3e24c30439a3` (v1 00602), `cap_b4050c3f8dcd` (v3b 00491) |
| R6 | **Unresolved deductible not surfaced** — no engine size, nothing in the referral says so | **NEW** | 4 → 0 → 0 | 2 → 0 → 0 | Quietly under-informs | `cap_68907ac851af` (v1 00483) |
| R7 | **"The wording is silent" though an annexure answers** (Week 8 modes 1/5) | no (carried) | 0 → 1 → 0 | 0 → 1 → 0 | **Wrongly denies or pays** | `cap_d666d6e5726c` (v2 00541) |
| R2 | **Right chunk, wrong clause label** — the citation names the chunk's *first* heading, not the clause where the fact sits | **NEW** (chunker × citation contract) | 5 → 4 → **3** | 4 → 4 → **2** | Misleads — trust cost | `cap_fb53ff4f85f2` (v3b 00584), `cap_2f07087bd0c7` (v3b 00496) |
| R5 | **Guard replaces adjuster-facing text with "[withheld: …]"** | **NEW** (guard × summariser) | 6 → 6 → **10** | 5 → 6 → **9** | Annoys — the adjuster loses the prose | `cap_d4c196813418` (v3b 00578) |
| R3 | **Tool call rejected** — the model echoed the JSON schema as the argument | **NEW** (tool schema × prompt) | 17 → 0 → 0 | 6 → 0 → 0 | Costs laps and tokens | `cap_9fd6b2e632ce` (v1 00418) |
| R8 | **Unresolved co-payment not surfaced** — no age on file, `applies: null`, no flag on the referral (the health twin of R6) | **NEW — found in this re-score; present in v1 and v2 too** | 14 → 14 → **13** | 2 → 8 → **4** | Quietly under-informs, but counted even when the question never asks about co-payment, so it is the least felt | `cap_01533fa123ee` (v3b 00431) |
| — | *No failure observed* | — | — | 4 → 15 → **13** | — | `cap_cbdacc3cbf93` (v3b 00601) |

Primary column totals: v1 5+8+2+0+4+5+6+2+4 = **36**; v2 2+0+0+1+4+6+0+8+15 = **36**; v3b 6+2+0+0+2+9+0+4+13 = **36**.
**The earlier "no failure" figures (6 → 23) are superseded:** they did not know about R8; with it, 4 → 15 → 13.

## What the re-score says

- **The gate fixed what it targeted and moved the cost elsewhere.** R1 stays far below its first value (8 → 2) and R3 and R7 are 0, but **R4 went 2 → 6 and R5 6 → 10.**
  All six budget stops ran the extra "What is not covered" search the gate forces (v2: 0 of 2 had it), all six had a blocked referral, and none of the 21 runs
  without a blocked referral stopped on the budget. The extra search puts a full section into the prompt that is resent every lap (SEAMS S23).
  The final system passes 33/36 assertions against 35/36 for v2, and the gap is these modes plus S17.
- **R5 is partly a guard false positive made likelier by the gate.** In **5 of the 10** withheld packets the only word the guard matched was "covered", and the model's
  final text uses that word only inside the clause title "What is not covered" (00423, 00442, 00509, 00514, 00606): a heading, not an outcome. Because the gate makes the model read and name
  that section, packets cite it far more often (9 of 27 non-exclusion questions, against 1 of 27 in v2 — my split of the 27 is by hand). The other five are real matches or
  borderline ones ("payable", "admissible", "covered for 3 years", "are excluded"). The guard is the compliance line, so I have not loosened it; this is the price, now measured.
- **R6 is fixed and its twin was missed.** The deductible flag works in all 4 runs that need an engine size. But the flag code (`unresolved_flags` in `src/agent/triage_agent.py`)
  only knows the deductible; a health claim with no age on file carries `co_payment: applies null, needs insured_age` unflagged — **13 of 36 runs in v3b, 14 and 14 before.**
  I missed it for two passes because I defined R6 through the assertion that checks the deductible. Caveat: R8 is counted whether or not the question needs the co-payment
  (a cancellation-refund question gets it too), so its raw count overstates how often it matters. It is not fixed.
- **R1 is back at 2, both S17.** 00491 and 00584 cite a base clause that an endorsement amends, because the amendment map misses 5 of 16 amendments. In 00491 the referral and summary state
  **48 hours, the base figure**, to an adjuster. v2's 0 was not a closed mode: the map was unchanged between the runs.
- **R2 survives the chunking change.** 3 runs (00423, 00496, 00584): the cited chunk's label is its first heading and the fact the summary uses sits under a later one. Structured chunking changed the chunk
  boundaries but not the labelling rule; 16 of 55 chunks hold more than one heading. v3b 00606, hand-coded R2 on v2, no longer counts: its 50% tyre fact now has a correctly labelled citation.
- **The suite still misses most of it.** 23 of 36 v3b runs show a mode, and **20 of those 23 passed every assertion.** Excluding R8, which the first pass did not have: 19 and 16, against 13 and 12 on v2.
  Of the three failing assertions, one is R4 (00468) and two are R1 (00491, 00584); nothing in the suite counts R2, R5, R8 or the budget stops that still produce a referral.
- **No new mode appeared on the final system.** The new observations — the gate's search eating the budget, the guard matching a heading — are causes of R4 and R5, not separate failures; I counted them as such.

## Old (Week 8) modes, re-scored on the integrated system

| Week 8 mode | Week 8 | v1 + v2 (72 runs) | v3b (36 runs) |
|---|---|---|---|
| 1 Refuses though the answer was retrieved | 25% | none seen; nearest is R7 (1 run) | none seen; R7 = 0 |
| 2 Gives the figure, drops the limiting condition | 15% | **not measured here** | **not measured** |
| 3 One wrong document fills every slot | 15% | none noticed; retrieved-but-uncited slots not counted | **not re-checked** |
| 4 Placeholder banner cited | 10% | **0 of 72** | **not re-checked** |
| 5 PDF table as a run of headings | 5% | recurs once as R7 | R7 = 0 |

## Also seen, not modes — not re-counted on v3b

Duplicate referral (1 run in v1, 0 in v2) · redactor corruption S14 (4 v1 packets, 0 v2) · provider outage (10 runs excluded from all counts, S15 fixed).
Only valid v3b rows are counted (outage rows with 0 tokens are set aside).

## Limits of this table

One reader, no second coder · the same 36 claims scored three times, so the three columns are not independent samples and one run per claim means a change of two or three runs is within noise
(the R4 and R5 movements are larger than that, but I have one run each) · R2 and R7 are my judgement against chunk text · the modes were named from v1 and v2 runs, then R8 added on seeing v3b, so they fit
these runs · the R5 "title-only" count is mechanical (every guard hit is "covered", and the word occurs only inside a "not covered" title in the final step's text) and I checked the five by eye ·
severity is my ranking, not the client's · R8's priority is last by my choice and changes the primary columns (it is why v2's "no failure" fell from 23 to 15) ·
the guard-borderline phrasings (v2 00442, 00567) remain uncounted.
