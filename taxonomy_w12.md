# Failure taxonomy — integrated system (Week 12)

**Sample:** census of all 72 runs — the 36 eval claims, first integrated run (`triage-v1`) and final run
(`triage-v2`). **Read:** by hand, one observation sentence per run, *before* any mode existed
(`taxonomy_w12_notes.md`, verbatim). **Counted by:** `eval/taxonomy_w12.py` (5 modes mechanical from
saved data; R2 and R7 hand-coded, named below). One reader — me — so not independent.

**Primary mode** = the one an adjuster would feel most, by the priority R4 > R1 > R6 > R7 > R2 > R5 > R3,
so each run is counted once and the column sums to 36. **Affected** counts every occurrence and overlaps.

| # | Failure mode | New from integration? | Affected v1 → v2 | Primary v1 → v2 | Severity | Example trace |
|---|---|---|---|---|---|---|
| R4 | **Empty packet** — the loop runs out of tokens or laps, no Final Answer, nothing cited; a forced referral still reaches the adjuster | no (agent loop × budgets) | 5 → 2 | 5 → 2 | Annoys the adjuster — nothing false is stated, the work is simply not done | `cap_7a5dfb3ca177` (v1 00468), `cap_35f4fbc3c0b5` (v2 same claim, 12 laps) |
| R1 | **Superseded clause cited next to its replacement** — two conflicting figures in one packet | no (Week 6 version blindness, found by integration) | 8 → **0** | 8 → **0** | **Wrongly pays** — adjuster may pick the 1,000 deductible when 1,500 applies | `cap_3e24c30439a3` (v1 00602) |
| R6 | **Unresolved number not surfaced** — no engine size, deductible blank, nothing in the referral says so | **NEW** (claim file × limits tool × referral) | 4 → **0** | 2 → 0 | Quietly under-informs — the adjuster can mistake "blank" for "none" | `cap_68907ac851af` (v1 00483) |
| R7 | **"The wording is silent" though an annexure answers** — Week 8 modes 1/5 recurring | no (carried) | 0 → 1 | 0 → 1 | **Wrongly denies or pays** — tells the adjuster the policy has no answer | `cap_d666d6e5726c` (v2 00541) |
| R2 | **Right chunk, wrong clause label** — a citation names the chunk's *first* heading, not the clause where the stated fact sits | **NEW** (chunker × citation contract) | 5 → 4 | 4 → 4 | Misleads — the adjuster is sent to clause 9 for a clause 8 fact; trust cost | `cap_06e1e9611841` (v2 00584), `cap_3899a978f776` (v2 00606) |
| R5 | **Guard replaces adjuster-facing text with "[withheld: …]"** — summary, reason or a fact line is blank | **NEW** (compliance guard × summariser) | 6 → 6 | 5 → 6 | Annoys — the compliance rule is kept, but the adjuster loses the prose | `cap_288af0834d12` (v2 00418) |
| R3 | **Tool call rejected** — the model echoed the JSON schema (`{"type": "room rent"}`) as the argument | **NEW** (tool schema × agent prompt) | 17 → **0** | 6 → 0 | Costs laps and tokens; 2 of the 5 v1 budget stops also had a rejected call | `cap_9fd6b2e632ce` (v1 00418) |
| — | *No failure observed* | — | — | 6 → **23** | — | `cap_fde18a29a98e` (v2 00601) |

Primary column totals: v1 5+8+2+0+4+5+6+6 = **36**; v2 2+0+0+1+4+6+0+23 = **36**.

## What the taxonomy says that the pass rate does not

- **The suite is blind to most of what is left.** v2 passes 35/36 assertions, but **13 of 36 runs show a
  mode, and 12 of those 13 passed every assertion.** The suite measures R1 and R6 — both now 0 — and
  nothing for R2, R4, R5 or R7. We fixed what we measured.
- **R5 did not move (6 → 6).** The guard is the compliance line, so this is its price: 1 run in 6 reaches
  the adjuster with a hole where the summary should be. Nothing in the eval counts it.
- **R2 is a mismatch between two weeks' work.** 16 of 59 index chunks hold more than one clause heading, and
  16/36 (v1) and 17/36 (v2) packets cite one. In 5 → 4 of them the prose states a fact from a *later*
  heading while the citation shows the *first*. Example: v2 00606's cited chunk is labelled "No Claim Bonus
  protection" but its second section is the one stating the 50% tyre limit remains in force.
- **The same assumption sits under the S12 fix and its assertion.** Both read the clause number from the
  first heading. 2 of the 31 base-document chunks hold an amended clause under an unamended heading
  (`PW-HEALTH-002::3`, `PW-CLAIMS-003::6`); 6 of 72 packets cite one. I have not shown that any relied on
  the superseded text — the point is that neither the fix nor the check would notice.

## Old (Week 8) modes, re-scored on the integrated system

| Week 8 mode | Week 8 | Now (72 runs) |
|---|---|---|
| 1 Refuses though the answer was retrieved | 25% | none seen while reading the 72; the nearest is R7 (1 run) |
| 2 Gives the figure, drops the limiting condition | 15% | not separately counted — **not measured here** |
| 3 One wrong document fills every slot | 15% | no run's citations came from an unrelated document that I noticed; **retrieved-but-uncited slots were not counted** |
| 4 Placeholder banner cited | 10% | **0 of 72 packets** cite one (6 banner chunks exist in the index) |
| 5 PDF table as a run of headings | 5% | recurs once as R7 |

## Also seen, not modes (too rare or not about the answer)

- **Duplicate referral:** 1 run in v1 (00608, `cap_1ba740483b7f`) created two referral records for one claim;
  the code does not stop a second `refer_to_adjuster`. 0 in v2.
- **Redactor corruption (S14):** `[REDACTED]` fragments inside 4 v1 packets and 0 v2 (00483, 00541, 00601, 00607).
- **Provider outage:** 10 runs (9 claims) ended with no referral (S15, fixed); excluded from the 72 here.

## Limits of this table

One reader, no second coder · the same 36 claims scored twice, so v1 and v2 are not independent samples ·
R2 and R7 are my judgement against chunk text · the modes were named from these 72 runs, so they fit
these 72 runs · severity is my ranking, not the client's · the guard-borderline phrasings (v2 00442
"excludes non-medical items", v2 00567 "applies to these facts for the adjuster to weigh") are **not** counted
because I cannot tell whether they are violations.
