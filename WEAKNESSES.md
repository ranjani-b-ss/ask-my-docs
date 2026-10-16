# Top 3 weaknesses

**Written 2026-10-12, after the 36-case eval — not before it.** The brief asks for weaknesses
written down before anyone asked; I can't honestly claim that, so here is exactly what the record
shows. `SEAMS.md` carries timestamps: the roots of weakness 2 (S3 shipped contracts state a
decision, S8 redactor gaps, S9 guard hole) were logged on **2026-10-08/09, before the eval ran**.
Weaknesses 1 and 3 were **not predicted**: 1 surfaced from one v2 failure, 3 from reading the
brief's hostile questions against what I log. Ranked by how much a client would care.

**Refreshed 2026-10-16 on the final system (v3b).** The ranking and the original evidence are unchanged; each weakness carries a dated *Update* with the v3b numbers, and a new section at the end says what the
re-measurement turned up and what I would re-rank. Numbers marked v3b come from `eval/capstone_results_v3b.json`, `taxonomy_w12.md` and the traces.

## 1. The system proves the right *version*, not the right *clause* — and its clause labels can mislead

Every check I run asks "is this the wording in force on the loss date?" None asks "does this
clause answer the adjuster's question?" And reading the traces showed the label itself is unreliable:
a citation carries the chunk's *first* heading, and 16 of 59 chunks hold more than one clause (16 of 55 after the move to structured chunking).

- **Evidence.** CLM-2026-00606 (tyre sub-limit), trace `cap_3899a978f776`: the packet cites only
  `END-2026-01::5`, labelled "7. New Clause 6A — No Claim Bonus protection". **Correction, 2026-10-12:** my first
  version of this file called that an irrelevant clause. It is not — that chunk's second section, "8. Unchanged
  provisions", states that the 50% tyre limit remains in force, which is the answer. What is wrong is the *label*
  (the first heading) and that the gold wanted the base clause. The same pattern shows in 5 v1 and 4 v2 runs
  (`taxonomy_w12.md` R2), e.g. v2 00584, `cap_06e1e9611841`: the cited "Co-payment" chunk is where a 30-day
  reimbursement window is stated, under its next heading. Only 6 of the 36 cases carry citation gold, so the
  other 30 cannot detect a wrong-clause citation at all.
  The S12 fix and its assertion share the first-heading assumption: 2 of 31 base chunks hold an amended clause under an
  unamended heading, so neither would notice a superseded clause cited through one of them.
- **Frequency.** Label mismatch observed in 4 of 36 final runs (11%); 17 of 36 cite a multi-heading chunk. Whether the
  *content* is relevant is not measured at all.
- **Update, 2026-10-16 (v3b).** Label mismatch in **3 of 36** final runs (00423, 00496, 00584; `taxonomy_w12.md` R2); 00606 no longer counts because its tyre fact is now also cited under the correct
  motor label. Structured chunking changed the boundaries, not the labelling rule, so the weakness stands. The amendment-map version of it got *worse to see*: **2 of 36 final runs cite a clause an endorsement amends (00491, 00584)**
  because the map, built from each chunk's first heading, misses 5 of 16 amendments (S17); in 00491 the retrieved passages never included the amending endorsement, so the packet states the base 48 hours — and a groundedness judge
  that sees only the retrieved context cannot detect that either.
- **Why it matters.** A wrong-but-well-formed citation reads as authoritative to an adjuster.
- **What fixes it / shows it fixed.** Label each cited chunk with *every* heading it contains (or chunk one clause per chunk)
  and make the S12 marker read all of them; gold *clauses*, not just documents, on every case; the judge on the
  integrated outputs with its agreement rate against hand labels (done on v1/v2 and on v3b — `EVAL_REPORT.md` §8, §8b — but it checks groundedness in the retrieved context, not that the right clause was retrieved). Shown fixed when R2 reads 0 on a re-count and
  the blind-spot chunks are marked.

## 2. The compliance and PII lines are pattern checks, and I can't measure what they miss

"Never state a coverage decision" and "no names, addresses or injuries in logs" are both enforced
in code (`src/triage_guard.py`, `src/redact.py`) — but by phrase lists, cue words and an injury word
list.

- **Evidence.** The model *tried* to state an outcome in **13 of 36 cases** (28 attempts in v1, 22 in
  v2, e.g. trace `cap_288af0834d12`: "covered" in the summary). The guard replaced all of them, so
  the shipped rate is 0 — **by construction**, which proves nothing about phrasings the patterns
  don't know. Two passed that I cannot classify: v2 00442 "excludes non-medical items" (describing a clause, or deciding?)
  and v2 00567 "applies to these facts for the adjuster to weigh" ("this will be honoured", "we will pay"). The PII scrubber was tested on 9 invented
  claims and a handful of FNOLs; it already produced two bugs of its own (S14: it corrupted trace ids
  and amounts) before one real test caught them.
- **Update, 2026-10-16 (v3b).** The model tried to state an outcome in **19 of 36** final runs (**39 attempts**, twice the v2 count — it can now see the full exclusion list). The guard replaced all of them. It also over-blocks:
  in **5 of the 10** packets that reached the adjuster with a `[withheld …]` hole, the only word it matched was "covered" and the final text used it only inside the clause title "What is not covered" — a heading, not an outcome.
  So the guard's two error directions are now both visible: it blanks headings (counted), and it may miss phrasings it has no pattern for (not countable). I have not loosened it.
- **Frequency.** Unknown by design: a miss is invisible to the check that would count it.
- **Why it matters.** This is the compliance rule the whole brief is built around.
- **What fixes it / shows it fixed.** An adversarial paraphrase set for the guard and a
  held-out PII set of realistic FNOLs, reporting the miss rate; a second, independent check (a model
  or a human-labelled sample) on a random sample of shipped packets.

## 3. An answer from the agent path cannot yet be reproduced and proven

The brief's regulator question: *reproduce that exact answer — same wording version, same retrieved
context, same model — and prove it.* The Week 11 replay tool does this for the plain RAG path. It has
**not** been built for the triage agent.

- **Evidence.** The trace stores chunk ids with content hashes, the model name, and each lap's raw
  output — but **not** the tool observations the model saw (deliberately: wording passed through the
  redactor was being corrupted, S14). And `prompt_sha` doesn't cover the tool block (S16: v1 and v2
  report the same hash `8343a85b02d6` for different prompts). Temperature is 0.0, but the model id is
  an alias and nothing pins it. **Update, 2026-10-16:** unchanged — S16 is still open, and the final system added a prompt version (`triage-v3`) whose hash still does not cover the tool block.
- **What I can claim.** Which chunks, at which versions, were retrieved — reconstructable from ids.
  **What I can't:** that the model received byte-identical input, or would give the same answer.
- **Why it matters.** "Why was this claim handled this way, eighteen months on?" is a real audit
  question and today the honest answer is "partly".
- **What fixes it / shows it fixed.** Store a hash of the full transcript each lap; fix S16; extend
  `eval/replay_trace.py` to the agent and replay a seeded sample of 10 traces, reporting how many
  rebuild byte-identical input and how many reproduce the packet's citations and numbers.

---
Also known, not in the top 3: single model provider with no degradation path (S15 fixed; the 240 s
dead-provider wait is not — `10X_PLAN.md`); all data synthetic; one run per eval case.

## What the final-system re-measurement added (2026-10-16)

Written after re-scoring the taxonomy and re-running the judge on v3b, so it was not predicted.

- **Unfinished packets are the weakness a client would feel first, and I ranked it nowhere.** 6 of 36 final runs stopped on the 30,000-token budget and delivered an empty packet with a forced referral; **5 of those 6 passed every
  assertion** (R4, SEAMS S23). All six had run the extra search the exclusions gate forces. The suite cannot tell an unfinished packet from a finished one. If I re-ranked today this would be second, above weakness 2.
- **Two modes the suite never counted.** R5 (the guard's `[withheld]` holes: 10 of 36) and R8 (an unresolved co-payment with no flag on the referral: 13 of 36, present since the first run and missed by my own taxonomy for two passes, because I had
  defined the sibling mode through the one assertion that checks the deductible). The R8 flag is now set in code and tested, but not yet re-measured.
- **20 of the 23 final runs that show a failure mode passed every assertion.** That is weakness 1 and 2 restated on the final system: the suite measures what I wrote it to measure.
- **The fixes moved the problem.** The gate that fixed the exclusion cases raised R4 (2 → 6) and R5 (6 → 10); the parser fix and the prompt hygiene removed R3 and R7. A fix is not shown by one number; the taxonomy is what shows it.
