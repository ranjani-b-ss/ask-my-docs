# Eval report — Claims Triage & Coverage Assistant (DRAFT)

> **Read first (updated 2026-10-14).** Sections 1–8 below were produced under the capstone prompt `triage-v2` on the legacy `recursive` index with no
> exclusions gate. The current system is `triage-v3` + `structured` chunking + the gate (SEAMS.md S21), and **§10 reports its 36-case run: 32/36 = 89%, down
> from 35/36 = 97%.** The trajectory eval was repeated for v3; the taxonomy (hand-read) and the judge validation were **not** and still describe v1/v2
> outputs. §10 says what caused each new failure.

36 claim files · model `gemini-3.5-flash-lite` · one run per case · all data synthetic.
Produced by `eval/run_capstone_eval.py` (deterministic assertions only — no model grades anything
in this section). **Draft:** the final non-coverage list is still to come and is marked PENDING; judge agreement is in §8.

## 1. The number that moved

**Wrong-version citation rate** — a packet that cites a clause an endorsement already amended, or an
endorsement not yet in force on the loss date.

| | cases | rate | 95% interval (Wilson) |
|---|---|---|---|
| before (v1, `triage-v1`) | 8 / 36 | 22% | 12%–38% |
| after (v2, `triage-v2`) | 0 / 36 | 0% | 0%–10% |

All 8 "before" cases cited a clause that an in-force endorsement had amended (the "superseded but
still in force" case) — none cited a not-yet-in-force endorsement, because the date filter already
removed those at retrieval. The interval on the "after" figure is wide: 0 of 36 does not show the
rate is zero, only that it is probably under 10%.

## 2. Pass rate by assertion (v1 corrected → v2)

| assertion | v1 | v2 |
|---|---|---|
| never_states_coverage | 36/36 | 36/36 |
| referral_present | 36/36 | 36/36 |
| in_force_checked | 36/36 | 36/36 |
| citations_name_version | 36/36 | 36/36 |
| citations_in_force | 36/36 | 35/36 |
| citations_grounded | 36/36 | 36/36 |
| superseded_not_cited | 28/36 | 36/36 |
| numbers_distinct_and_correct | 32/36 | 36/36 |
| pii_clean | 36/36 | 36/36 |
| **every assertion** | **26/36 = 72%** | **35/36 = 97%** |

## 3. By group — the groups, not the average

| group | n | v1 | v2 |
|---|---|---|---|
| w12-boundary (loss the day before / the day of an endorsement) | 5 | 3 | **5** |
| w12-in-force-failure (lapsed, not yet started) | 2 | 2 | 2 |
| w12-pii | 1 | 1 | 1 |
| w12-three-numbers | 1 | 1 | **0** |
| w6-clean-baseline | 5 | 3 | 5 |
| w6-drops-limiting-condition | 6 | 3 | 6 |
| w6-pdf-table-mangled | 3 | 3 | 3 |
| w6-placeholder-banner-cited | 3 | 2 | 3 |
| w6-refuses-answer-present | 5 | 4 | 5 |
| w6-wrong-document-retrieved | 5 | 4 | 5 |

*"How many cases have a loss date between two endorsement versions, and what do those score?"* —
**5** (CLM-2026-00601, 602, 607, 608, 609). v1 scored **3/5**: both *effective-day* cases (602, 608)
cited the superseded clause next to its replacement. v2 scores **5/5**.

## 4. What still fails

**CLM-2026-00606 (tyre sub-limit, v2).** The packet cites only `END-2026-01::5`, which the citation labels
"No Claim Bonus protection" and never the base-policy tyre clause the gold expects. **Correction (2026-10-12):** an
earlier draft here called that chunk irrelevant. Reading the chunk showed its second section, "8. Unchanged
provisions", states that the 50% tyre limit remains in force — so the cited text does answer the question; the *label*
shows only the first heading, and the gold is stricter than the answer needs. This is mode R2 in `taxonomy_w12.md`.
The three numbers are correct (from `get_limits`). Not caused by the superseded-clause filter (nothing was dropped).
One run.

## 5. What changed between v1 and v2, and what that does and does not prove

Bundled in v2: the prompt's tool signatures (S10), a code-set `unresolved:` flag (S11), superseded-clause
dropping (S12), the redactor fix (S14), and the forced-referral fix (S15). I ran **no ablation**, so each
improvement is attributed to a mechanism by reading the failures, not by turning one fix off.
- 17 cases had a rejected `search_wording` call in v1; **0** in v2 (S10).
- Unflagged unresolved deductible: 4 cases in v1; 0 in v2 (S11).
- The S12 check and the S12 fix both lean on the corpus's "Amendment to Clause X" headings — they
  parse them independently, but a corpus that words amendments differently would defeat both.

One assertion was changed after seeing v2: the lapsed-policy check wanted the literal phrase "in force"
and rejected the correct reason "after the policy's in-force window ended" (hyphen). It now ignores
hyphens (test added). As-run result **33/36**, corrected **35/36**; the as-run file is kept in
`eval/capstone_results_v2_asrun.json`. The same assertion set scores v1 and v2.

## 6. Reliability and the compliance line

| | v1 | v2 |
|---|---|---|
| model **attempted** to state an outcome (guard replaced it) | 28 | 22 |
| outcomes stated in the shipped packet | 0 | 0 |
| failed tool calls | 17 (in 17 cases) | 0 |
| cost per claim / p50 latency | $0.0038 / 25.5 s | $0.0036 / 24.6 s |

The guard's 0 is by construction (it replaces what it catches). **The 22 attempts are the honest
number:** in 13 of 36 cases (36%) the model tries to state an outcome at least once (28 attempts in v1, 22 in v2) and is stopped by code.

**Trajectory** (`eval/cap_trajectory_eval.py`, gold from the registry): tool-choice accuracy 90.5% → 97.3%;
clean route 17/36 → 31/36. In all 5 unclean v2 routes the model tried to refer before searching or
fetching limits; the gate blocked it and the model recovered. 2 of 36 cases have the lapsed route as gold.

## 6b. What the 36 passing runs still hide

`taxonomy_w12.md` (all 72 runs read by hand): the final run shows a failure mode in **13 of 36** runs, and **12 of those
13 passed every assertion** here. R1 and R6 (the modes this suite measures) went to 0; R2 (citation label shows the chunk's
first heading, 4 runs), R4 (empty packet, 2), R5 (guard blanks the adjuster's summary, 6) and R7 (1) are not measured by
any assertion. One reader, not independent.

## 7. What this suite does not measure — PENDING FINAL LIST

Drafted so far: repeat-run variance (one run per case) · whether the cited wording actually answers
the adjuster's question (only that it is the right *version*) · real claim text, real policies, real PII ·
any model other than `gemini-3.5-flash-lite` · behaviour under concurrent load · paraphrased outcome
statements the guard's patterns do not recognise · amendments not worded "Amendment to Clause X".

## 8. Judge agreement

**What is judged.** The one thing the 9 assertions cannot check: is the adjuster-facing prose (summary, referral
reason, "why" lines) grounded in what the model was shown — the retrieved passages and the limits tool? Inputs are
rebuilt from the trace alone and each passage is checked against the content hash the trace stored. Prompt:
`eval/judge_cap_v1.txt` (sha `e075e1818e0e`), judge model `gemini-3.5-flash-lite`. Protocol written before the
second prompt was run: `eval/judge_cap_protocol.md`.

**Hand labels:** 70 (`eval/labels_cap_70.json`, sha256 frozen in `labels_cap_70.sha256`, enforced by a test).
Written by me, from the rebuilt context, before any judge call. **Not independent**: I also built the system, wrote
this judge's prompt and wrote the assertions. Two v1 runs are excluded because their stored context hash was corrupted
by S14 and cannot be verified.

| split | n | agreement | 95% interval | always-GROUNDED baseline | Cohen's κ | real errors caught | false alarms |
|---|---|---|---|---|---|---|---|
| **test (held out, 3 runs)** | 36 | **35/36 = 97.2%** | 85.8–99.5% | 97.2% | **0.65** | 1 / 1 | 1 |
| dev (prompt chosen on it, 3 runs) | 34 | 30/34 = 88.2% frozen · 31/34 = 91.2% revised | 73–95% · 77–97% | 97.1% · 94.1% | 0.30 · 0.53 | 1/1 · 2/2 | 4 · 3 |
| **pooled** | 70 | **65/70 = 92.9% frozen · 66/70 = 94.3% revised** | 84–97% · 86–98% | 97.1% · 95.7% | **0.42 · 0.57** | 2/2 · 3/3 | 5 · 4 |

**Read this before quoting any of it.**
- **The ≥85% bar is met — and means little.** Only 3 of the 70 outputs are UNGROUNDED, so an always-GROUNDED "judge" scores
  95.7–97.1%. The judge's raw agreement is *below* that baseline on the pooled set. The honest figure is κ ≈ 0.4–0.6 (moderate).
- **It is a high-recall, low-precision screen.** It caught all 3 real errors, but it raised 7 UNGROUNDED flags on natural outputs
  and only 2–3 were real (frozen / revised labels): precision ≈ 29–43%. With 3 positives, "caught 3/3" has a 95% interval of roughly 44–100%.
- **One label was revised after seeing the judge** (`labels_cap_70_revisions.json`): v1 CLM-2026-00479 GROUNDED → UNGROUNDED. The
  summary says "policy limit is INR 10,00,000" while the packet's own limits result says 5,00,000. My labeling sheet had
  truncated that tool result, so I missed it. Revised only for a verifiable factual error; both figures are shown above.
- **Prompt iteration.** Exactly one revision (`judge_cap_v2`), from dev evidence only. Chosen by a rule written beforehand
  (fewer dev disagreements; tie → v1): they tied at 2, so **v1 was kept and frozen**. v2 fixed a table misread but then
  *missed* the real v2 00455 error (κ −0.04) — a worse kind of failure than a false alarm. Test was run once, after freezing.
- **The judge and the system under test are the same model family** (Gemini lite); a stronger or different judge was not
  available (other models returned 503 during the run). Self-preference is untested.
- **Stability:** 5 of 100 repeated cells flipped between runs; 1 provider error (majority of remaining runs used).

**Planted-error set** (`eval/planted_cap.json`, 24 minimal edits to real packets + 6 reworded controls; separate from the
natural figure): recall **24/24** (stale 8/8, contradiction 9/9, invented figure 4/4, rule-misfit 2/2, false absence 1/1),
controls flagged **0/6**. These are errors I thought of and they are blunt, so this shows the judge *can* see an error, not
that it sees the ones the system actually makes. An edit that plants a not-yet-in-force figure with the later passage shown
could not be built from the real packets and is not covered.

**What it found that nothing else did.** Three real defects in the outputs, **all of which passed every one of the 9
deterministic assertions**: v2 CLM-2026-00455 says the vehicle is "within the 5-year age limit" (first registered 2018);
v2 CLM-2026-00609 computes a limit "based on a sum insured of INR 5,000,000" (the file says 5,00,000); v1 CLM-2026-00479
states a policy limit that contradicts its own limits result. The last is partly a data seam (SEAMS.md S20).

**What the judge does not see:** wording that was never retrieved (an absence claim is judged against the shown passages only —
the annexure case, R7, is invisible to it), which heading a citation shows (R2), and anything in the claim file it is told
not to judge.

## 9. Bonus — loss-date-aware retrieval

See [STRADDLE_BONUS.md](STRADDLE_BONUS.md). Retrieval level: 7 of 8 day-before straddle cases are red without the loss date, 0 of 8 with it. End to end (1 run per cell, 5 claims): without the filter all 5 were shown wording that did not yet exist and 3 cited it; with the filter 0 of 5 for both. Cost on 22 non-straddling control questions: 0 hit@3 lost (upper bound ≈ 11%), 16% of rank-1 chunks reshuffled. Not fixed by the filter: effective-day superseded wording (2 of 8 stay red).

## 10. The current system (`triage-v3` + `structured` chunking + exclusions gate) — run 2026-10-14

Same 36 claims, same assertions, same model (`gemini-3.5-flash-lite`), one run per case. `eval/capstone_results_v3.json`.

| | v1 (corrected) | v2 | **v3 (current)** |
|---|---|---|---|
| every assertion | 26/36 = 72% | 35/36 = 97% | **32/36 = 89%** |
| `citations_in_force` | 36/36 | 35/36 | 34/36 |
| `superseded_not_cited` | 28/36 | 36/36 | 35/36 |
| `numbers_distinct_and_correct` | 32/36 | 36/36 | 35/36 |
| completed with a Final Answer | 31/36 | 34/36 | 31/36 |
| stopped on a budget | 5 | 2 | **5** |
| tokens per claim, median / p90 | – | 20,962 / 27,367 | **28,284 / 32,758** |
| cost per claim | $0.0038 | $0.0036 | $0.0044 |
| model attempted an outcome statement | 28 (13 cases) | 22 (13 cases) | **44 (20 cases)** |
| trajectory: clean route · tool-choice accuracy | 17/36 · 90.5% | 31/36 · 97.3% | 24/36 · 94.9% |

**v2 → v3 is a drop of 3 cases on n = 36, one run each — not distinguishable from run-to-run variance.** It is reported as it is. The four failures:

| claim | what happened | cause |
|---|---|---|
| CLM-2026-00606 | token budget exceeded (31.6k > 30k) → empty packet | **the gate** (one blocked referral + an extra "What is not covered" search, whose chunks ride in every later lap) |
| CLM-2026-00607 | token budget exceeded (36.4k) → empty packet | **the gate** (searched the section first, then the co-payment clause) |
| CLM-2026-00567 | 12 laps, 8 of them `malformed`: the model wrote `ActionInput:` (no space) so the parser rejected it | **not this change** — a brittle parser (SEAMS S22), **since fixed**: re-run once, it passes in 6 laps / 16.5k tokens. The 32/36 above is the run before that fix. A full re-run with the fix was attempted and stopped by the model quota after 10 claims (`capstone_results_v3b.json`: 9 pass, 1 budget stop) — **there is no 36-case number for the fixed parser yet** |
| CLM-2026-00584 | cites `PW-HEALTH-002` clause 8 next to the endorsement that amends it | **not this change** — the S17 amendment-map gap (clause 8 is one of the 5 the map misses); v2 passed by variance |

**What the change did on the exclusion claims** (00509, 00514, 00567, 00561, 00442): the old prompt's phrases are gone — **0 of 62** logged queries quote them (v2: 4 of 89) —
and the model now writes its own ("alcohol intoxication under the influence", "What is not covered alcohol liquor influence"). On 4 of the 5 the governing clause
was still shown **and** cited; the fifth is the 00567 parser loop above. The gate fired on 11 claims and 31 queries now name the section. So removing the hints did
not, in this run, break the exclusion claims — with one run each.

**Costs to take seriously.** (1) The median run now uses 28.3k of a 30k token budget — the budget binds, which is what turned two gate-driven extra searches into empty
packets; either the budget, or the habit of resending every retrieved chunk on every lap (95% of tokens are prompt), has to change before this scales (see 10X_PLAN.md).
(2) The model tried to state an outcome **twice as often** (44 vs 22) once it could see the full exclusion list; the guard replaced all of them, so none shipped, but
"the guard's 0 is by construction" matters more now. (3) The gate can add a lap or a stall; it does not make the model's reasoning better, it makes the evidence reach it.

**Still not repeated on v3:** the hand-read taxonomy and the judge validation. The numbers in §§1–8 are v1/v2 results and stay valid as that.
