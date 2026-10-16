# Week 11 — Production: Observability, Cost & the Failure → Test Loop

## Task Set D · Insurance claims · Find the coverage answer that ignored an exclusion

Every number below came from real `react_agent.run()` calls against real claims today —
nothing here is asserted without `drill.md`, `trace.json`, `suite_red.txt`/`suite_green.txt`,
`cost_by_stage.md`, or `tenx.md` to back it. This file explains what they show, in what
order they were produced, and why.

---

## 1. The numbers, up front

| | |
|---|---|
| Time to find the planted failure | **00:45**, full-text content search — not blind, not squadmate-timed; cost-outlier slice (#1 of 11) confirmed afterwards, untimed (`drill.md`) |
| Suite, before the fix (v1 prompt) | **7/11 passed** (`suite_red.txt`) |
| Suite, after the fix (v2 prompt) | **8/11 passed** (`suite_green.txt`) — C-011, the targeted claim, flipped FAIL → PASS |
| Cost per query | **$0.00347**, 100% generation (`cost_by_stage.md`) |
| What breaks first at 10x | **the rate limit — already broken at 1x**, confirmed live twice (Week 10, and again this week) (`tenx.md`) |

A methodology note that applies to every number above: today's runs used
`gemini-3.5-flash-lite`, not the project's pinned `gemini-3.6-flash` — that model's
20-requests-per-day free tier ran out partway through this week's own work (my four hand-run
C-011 attempts on the pinned model almost certainly used it up — inferred from the order of
successes then 429s, not read off Google's counter), before the suite ran (see §7 and
`tenx.md`). Both the RED and GREEN suite passes used the *same* substitute model, so
the before/after comparison is fair even though it isn't on the originally pinned model.

---

## 2. No literal squadmate — what "planted" means here, honestly

This is a solo build, and the drill was **not blind**: I built the scenario and had already
read the full C-011 trace before starting the timer, as `drill.md` says up front. What
*is* real: a new claim (C-011) was added specifically to probe one exclusion bullet —
`PW-MOTOR-001` Clause 3's last item, "loss or damage occurring outside the geographical
area stated in the schedule" — that no prior claim in this project's whole history (Weeks
7-10) ever exercised. Before writing it, a **zero-LLM-cost** retrieval test confirmed the
gap was real: four natural phrasings of "accident while driving abroad" all missed the
clause; the clause's own wording retrieved it at 0.999 relevance. So a failure was
expected, not unknown.

C-011 was then run by hand four times (all ended `REFERRED` on budget or quota limits, none
with a clean answer) before the suite. The failure itself was live and unscripted, and the
confident "covered" Final Answer first appeared in the suite run. §4 is what the logs
showed once found.

---

## 3. Requirement 1 — the drill

Full writeup in `drill.md`. The short version: a naive search of the complaint's own
wording ("covered" + top-level `status=="PAYABLE"`) returned **3 false positives** and
missed the real trace entirely — its top-level status is `REFERRED`, not `PAYABLE` (the
loop's own safety net caught the bad Final Answer before it became the served status). The
timed find was a **full-text content search over nested step output**, not one of the five
listed slices: **45 seconds** by `date +%s.%N` brackets, but one of its queries used a phrase
I only knew from having already read the trace, so treat 00:45 as a lower bound, not a blind
time, and no squadmate timed it. The **cost-outlier slice** — sort today's real traces by
`usage.cost_usd` descending — was run afterwards, untimed, and puts the bad trace at **#1 of
11**, more than 4x the cheapest claim in the batch: the listed slice that would have found
it near-instantly.

---

## 4. Requirement 2 — the trace, and what it actually shows

`trace.json` is the full, real record. The honest finding is bigger than "missed an
exclusion":

1. **A confirmed retrieval gap.** `PW-MOTOR-001` Clause 3's 7-bullet exclusion list is split
   across two overlapping chunks by the chunker — `::4` holds 6 bullets, `::5` holds only
   the geographical one. Six real search queries across the live run (laps 2-7) retrieved
   `::4` or unrelated health-policy chunks; **`::5` is never retrieved, not once** — this is
   read directly off `retrieved_chunk_ids`, not inferred from the wrong answer.
2. **A hallucination this project hasn't documented before.** After repeated failed
   searches, the model's own `raw_output` on laps 5-7 contains *fabricated* clause text —
   a fictional "Endorsement 1 Clause 4 — accidents in Nepal or Bhutan are covered without a
   special extension" that exists nowhere in `corpora/insurance/` (checked against every
   real corpus file). The model invented a convenient exception and cited it as real.
3. **The internal Final Answer at lap 8 says exactly what the complaint describes**:
   *"The accident in Nepal is covered under Endorsement 1 ... no policy exclusions
   apply."* PAYABLE, INR 26,500. It never became the served answer only because
   `react_agent.py`'s own `payout_verified` gate rejected it (over a different check,
   `amount_matches`) and the loop then ran out of `max_tokens` before trying again — not
   because anything caught the *coverage* mistake by design.

Per-span latency, tokens, cost, `prompt_version`, `prompt_sha`, and every retrieved chunk id
are all in `trace.json` — see its `_spans` and `_annotations` for the readable version.

---

## 5. Requirement 3 — the eval case, and the suite RED then GREEN

**The eval case**: `src/agent/claims_store.py`'s new `C-011` entry plus
`eval/race_cases.yaml`'s matching gold answer (`NOT_PAYABLE`, exclusion clause
`PW-MOTOR-001 Clause 3`). `eval/run_claim_suite.py` is the suite — every claim in
`race_cases.yaml`, graded by the same rule every other claim-triage eval in this project
uses, run for real against `react_agent.py` (the system Week 10 recommended shipping).

**RED** (`suite_red.txt`, v1 prompt): **7/11 passed.** C-011 failed as expected
(`REFERRED`, gold `NOT_PAYABLE`) — confirmed, not assumed.

**GREEN** (`suite_green.txt`, v2 prompt, §6's fix applied): **8/11 passed.** C-011 now
passes (`NOT_PAYABLE`, matching gold exactly).

**The part the brief's own common-mistake list warns not to skip — did anything else
silently break?** The raw counts (7→8) hide as much as they show, so each of the other
three claims whose status changed was individually inspected, not just counted:

| claim | RED | GREEN | caused by the fix? |
|---|---|---|---|
| **C-011** | FAIL (REFERRED) | **PASS** (NOT_PAYABLE) | **Yes — this is the fix working.** |
| C-004 | FAIL (REFERRED) | PASS (NOT_PAYABLE) | No — unrelated claim, unrelated exclusion (no valid driving licence); the v2 prompt edit never touches this reasoning path. |
| C-007 | FAIL (REFERRED) | PASS (PAYABLE) | No — partial-exclusion/hire-car arithmetic, untouched by this fix. |
| C-001 | PASS | FAIL (REFERRED) | No — the v2 run got the *right* answer four times (laps 6-9, logged) but kept forgetting to call `compute_payout` first; budget ran out one lap before it self-corrected. The same `repeated_rejection`/skipped-tool-call risk Week 8 already documented, on a weaker model. |
| C-003 | PASS | FAIL (REFERRED) | No — the model inverted rule 3's own "excluded UNLESS Y" logic on the tyre clause, three times in a row. A rule-3 compliance miss, not anything rule 2 or rule 10 added. |
| C-010 | FAIL (PAYABLE, wrong) | FAIL (NOT_PAYABLE, wrong) | No — this is the project's own documented genuinely-ambiguous case (flood vs. mechanical failure); it has never passed reliably, Week 10 included. |

None of the five non-C-011 deltas trace back to the two lines changed in §6. All five are
pre-existing risk classes (budget exhaustion via repeated rejection, rule-3 logic
inversion, the C-010 ambiguity) surfacing because of real run-to-run variance on
`gemini-3.5-flash-lite` — not a regression this fix introduced. That conclusion is reached
by reading each trace, not by trusting the aggregate number, which is the entire point of
this requirement.

---

## 6. Requirement 4 — the fix, the version bump, canary and rollback

> **Superseded — see §9.** Review feedback correctly pointed out that this "fix" copied the policy wording into the prompt, which hands the model the answer. The cause below was wrong, and the fix has been replaced.

**Root cause, in one line**: rule 2 of `SYSTEM_PROMPT` enumerated specific trigger phrases
for five known exclusion types and never mentioned the geographical one, so the agent built
its search query from the claim notes' own vocabulary ("Nepal", "cross-border") — which
`§4` confirms never retrieves the governing chunk, only the clause's own wording does.

**The fix** (`src/agent/react_agent.py`, `PROMPT_VERSION` `v1` → `v2`):
- **Rule 2** now names the geographical exclusion explicitly and gives the exact phrase to
  search with: *"outside the geographical area stated in the schedule"* — not a paraphrase.
- **Rule 10** (new): never state a clause, figure, or exception not seen verbatim in a real
  Observation this run; after repeated failed searches, stop and REFER honestly rather than
  invent one. This targets §4's second finding (the hallucinated Nepal/Bhutan clause)
  directly — a fix at the prompt layer for the more dangerous of the two problems found,
  not just the one the brief's example names.

**Canary** (two lines): route 10% of new claims through `PROMPT_VERSION=v2` for 48 hours
alongside v1 on the rest, with `prompt_sha` logged on every trace so each arm is
unambiguous; promote to 100% only if v2's suite pass rate on a fresh run is >= v1's and no
new `rule 10 stop` fires on a claim v1 would have answered correctly.

**Rollback** (two lines): revert `SYSTEM_PROMPT_TEMPLATE` to the `v1` text (one `git revert`
of this commit) and redeploy; because every trace already logs `prompt_version` and
`prompt_sha`, every claim decided under v2 is identifiable after the fact and can be
flagged for manual re-review without guessing which requests are affected.

---

## 7. Requirement 5 — cost per query by stage, and what breaks first at 10x

Full numbers in `cost_by_stage.md` and `tenx.md`. Headline: **$0.00347/query, 100%
generation** — retrieval and tools are free local compute in this architecture, so there is
no real 3-way split to hide behind; the number people usually want to cut (retrieval cost)
is already zero. **What breaks first at 10x is the request-rate limit — and it's already
broken at 1x**, confirmed live twice (Week 10, and again this week): `gemini-3.6-flash`'s free tier is 20
requests/day, and this week's own 11-claim suite needs ~72 requests (6.5 calls/claim) to
run once.

---

## 8. What was deliberately left alone

- **The pinned model (`gemini-3.6-flash`) was not re-verified against this fix.** Its daily
  quota ran out partway through this week's work (my own four hand-run C-011 attempts almost
  certainly used it up — an inference from the order of events) before the suite ran; the
  suite passes ran on
  `gemini-3.5-flash-lite` instead, disclosed throughout rather than silently substituted.
- **C-010's ambiguity was not touched.** It is this project's own deliberately
  unresolvable case (Week 7 onward) and out of this week's scope.
- **C-001/C-003's weak-model failures were not chased down or "fixed."** §5 shows they are
  unrelated to this week's actual fix; patching them now would be solving a different
  week's problem under this week's banner.
- **`orchestrator.py` was not instrumented.** Week 10's verdict was to ship the single
  agent; this week's observability work follows that call.

---

## Bonus — wiring the drill shut

Not attempted this week: a second planted failure, timed against the first, needs a second
real live run and this key's daily quota is the one resource that does not reset within a
single working session (see §7). The one field named honestly as still missing:
**`input_type`** — this app serves exactly one request shape (motor claim triage), so there
was nothing to index yet; the moment a second request shape exists (health claims, a
different line of business), this is the field that will need adding before it becomes the
next drill's bottleneck.

---

## 9. Follow-up after review — the real cause, and what is and is not verified

**The feedback:** *"copying the policy wording into the prompt gives the model the answer, so fix the real cause and re-run the two
cases that broke."* It was right. v2's rule 2 quoted "outside the geographical area stated in the schedule" as the phrase to search
with — the clause's own words, for the exact case that exposed the failure. That would have turned C-011 green without fixing
anything, and does nothing for the next clause nobody quoted. It is **removed** (prompt v3 carries no such wording; a test pins it).

**Two real causes, found by measuring rather than assuming.**

1. **A chunking defect** — `drill.md` named it and I did not fix it. The corpus hard-wraps its lines and `recursive` packs *physical
   lines*, so the 8-bullet motor exclusion list (~1,050 chars vs an 800 target) was cut mid-bullet. Its tail — `…hire charges for a /
   replacement vehicle` and the geographical-area bullet — sat in a 253-character stub (`PW-MOTOR-001::5`) that starts mid-line. Those are
   the two cases that broke: **C-011** (geographical bullet) and **C-007** (the hire-car bill). Repair: a new `structured` strategy
   (`src/chunker.py`) — a bullet with its continuation lines is one atom; a clause up to 2× the target stays whole — built as a *separate*
   collection so Week 12's index, chunk ids and stored hashes are untouched. Exactly four sections change (motor exclusions, **health
   exclusions — the same defect, in a policy no test claim touches**, health reimbursement, definitions); a test pins that set.
   My first draft of this repair left an 18-character stub and hard-cut the definitions section; found by diffing the chunks, fixed.
2. **Nothing in the code required the exclusion list to be read.** Replaying the model's own logged queries (zero-LLM,
   `eval/chunk_fix_replay.json`): the chunk repair alone moves C-011 from **1/11 to 2/11** queries that put the governing bullet in the top 3,
   and C-007 from 1/6 to 1/6 — **not enough.** The Nepal/geographic phrasings still retrieve endorsement and definitions chunks, because the
   claim's vocabulary is not the clause's. What does reach it, on the new index and not the old, is the generic "what is not covered" query
   (both bullets exposed vs neither). So the agent now has a code gate, in the style of its existing ones: a decision is rejected until a
   retrieved chunk is the policy's "What is not covered" section (`AGENT_EXCLUSIONS_GATE`, default on). It names no wording.

**Verified now (no model):** 8 chunker tests (invariants + the exact blast radius) and 4 gate tests that drive the real `react_agent.run`
loop with a scripted model; the replay above; and that the prompt contains no geographical wording.

**The live re-run (2026-10-14; the first attempt on 2026-10-13 hit the Gemini quota and is set aside in `eval/chunk_fix_rerun_outage_NOT_RESULTS.json`).**
C-011 and C-007 × three arms × two runs, prompt v3 (no clause wording in it), `gemini-3.5-flash-lite`, graded by the suite's own grader.
**n = 4 per arm — a direction, not a proof.**

| arm | what is repaired | passes | governing bullet shown to the model |
|---|---|---|---|
| A | nothing (leak removed, old chunks, no gate) | **0 / 4** | 1 / 4 |
| B | chunk repair only | **2 / 4** | 1 / 4 |
| C | chunk repair + exclusions gate (shipped) | **3 / 4** | 3 / 4 |

Taking the wording out of the prompt and fixing nothing else fails all four, which is what you would expect if the wording had been doing the work.
Each repair moves the result the right way. With 4 runs per arm, 0/4 vs 3/4 is **not** statistically distinguishable (Fisher exact, one-sided
p ≈ 0.07), and single runs of a stochastic system vary: C-011 arm C run 2 failed.

Two things the runs showed that I did not expect:
- **The gate on the OLD index is satisfied by an incomplete list.** In arm A the model did retrieve the "What is not covered" section (`exclusions_read`
  true) in 3 of 4 runs, yet the governing bullet was shown in only 1 — the section's label was there, its tail sat in the stub. That is why the chunk
  repair and the gate belong together: the gate checks the section label, only the repaired chunk makes the label mean "the whole list".
- **The gate can stall.** C-011 arm C run 2 ended on `repeated_rejection`: the model resubmitted the same rejected Final Answer three times without
  searching for the exclusion clause (Week 8's known pattern), so the gate cost that run instead of fixing it. Arm B also had one such stall (C-007, run 2),
  from the existing payout checks. B run 1 of C-007 passed *without* reading the exclusions at all (the arithmetic from the notes was enough) — a pass the
  gate would have required it to earn.

**Same flaw elsewhere:** the v1 prompt's rule 2 still names five exclusion *categories* in plain words (left as it was). The Week 12 capstone's
triage prompt and `search_wording` tool description quoted exclusion wording verbatim; **that has since been removed** (`triage-v3`, SEAMS.md S21), and
the capstone now also reads the repaired `structured` chunking and has the same exclusions gate (S21). Neither capstone change has been re-evaluated
end to end — the quota is exhausted.

