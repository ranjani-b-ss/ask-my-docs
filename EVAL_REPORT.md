# Eval report — Claims Triage & Coverage Assistant (DRAFT)

> **Read first (updated 2026-10-18).** Sections 1–8 below were produced under the capstone prompt `triage-v2` on the legacy `recursive` index with no
> exclusions gate. The current system is `triage-v3` + `structured` chunking + the exclusions gate + the `ActionInput` parser fix (SEAMS.md S21, S22).
> **§10 reports its complete 36-case run: 33/36 = 92%** (v3 before the parser fix: 32/36; v2: 35/36). One run per case, so those differences are within noise.
> The trajectory eval was repeated; the taxonomy (hand-read) and the judge validation were **not** and still describe v1/v2 outputs.

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

## 7. What this suite does not measure

**In one sentence:** the suite checks that a packet cites the *right version* of the wording, states three separate numbers, names no person, and never states a coverage decision — it does
**not** check that the cited clause answers the adjuster's question, that the packet is useful to a human adjuster, or that any of it holds on real claims, real policies or real load.

Three tiers, so a reader can tell "unmeasured" from "measured badly" from "measured on the old system". The suite is 36 synthetic claims (21 health, 15 motor), loss dates 2026-02-10 to
2026-08-03, one run each, graded by 9 deterministic assertions I wrote; gold for numbers comes from a registry and limits table I generated from the corpus.

### A. Not measured at all

| # | What is not measured | Why it matters | What would measure it |
|---|---|---|---|
| A1 | **Whether the cited clause answers the question.** Only the *version* is checked; only 6 of 36 cases carry citation gold, so 30 cannot detect a wrong-clause citation. | A right-version, wrong-clause citation reads as authoritative (WEAKNESSES.md #1). | Gold *clauses* on every case; judge the cited text against the question. |
| A2 | **Whether an adjuster finds the packet useful.** No human adjuster has read one. "Useful", "neutral", "enough to act on" are untested. | The product is a hand-off to a person. | 10–20 packets rated by a real adjuster against the raw claim file. |
| A3 | **Real data.** Policies, claims, people, addresses and limits are all synthetic; the registry assigns a default sum insured per product. | Real narratives are messier; real registries disagree with narratives (S20). | A held-out sample of real, consented claim files. |
| A4 | **Prompt injection through the claim narrative.** The narrative is untrusted text sent to the model; Week 8's injection test targeted the older agent and was not run on the capstone. | The brief's own security concern. | Reuse `eval/injection_test.py`-style cases against `cli.py triage`. |
| A5 | **Misses of the compliance guard and the PII scrubber.** Both are pattern checks. The guard's pass rate is 100% *by construction*; a miss is invisible to the check that would count it. The scrubber was tested on 9 invented claims plus a few FNOLs. | This is the compliance line the whole brief is built on. | A paraphrase set for the guard; a held-out set of realistic FNOLs with a reported miss rate. |
| A6 | **Replay / audit.** Whether a past packet can be reproduced byte for byte (WEAKNESSES.md #3): tool observations are not stored; `prompt_sha` does not cover the tool description (S16). | The regulator question, "eighteen months on". | Store a transcript hash per lap; replay a seeded sample. |
| A7 | **Wrong or missing loss dates.** The system trusts the claims system's `loss_date`. Multi-day events, missing dates and corrected dates are not in the set. | Everything date-aware rests on that one field. | Cases with a wrong, missing and amended date. |
| A8 | **Amendments that are not worded "Amendment to Clause X"**, overlapping endorsements, an endorsement that supersedes another endorsement. The corpus has three endorsements and the amendment map already misses 5 of 16 (S17). | The version logic is only proven on this corpus's conventions. | A second corpus with different drafting conventions. |
| A9 | **Waiting periods and other date arithmetic.** The system surfaces the wording; it does not compute whether a waiting period has run. Whether the model applies it correctly is judged by no assertion. | Health decisions turn on it. | Gold for "has the waiting period run" on cases that depend on it. |
| A10 | **Concurrent claims.** One shared MCP session was probed only with concurrent *searches*, never concurrent *claims*; there is no worker pool (10X_PLAN.md). | The hailstorm scenario. | A load test of N claims in flight. |
| A11 | **MCP failure modes other than a dead model provider.** A server crashing mid-run, a tool timeout, malformed tool output, or a hostile tool description from another server are not tested. The foreign-client check (someone else's agent calling our server) has not been done. | Joining servers is the point of the capstone. | Fault injection on both servers; a foreign client run (fresh-eyes task). |
| A12 | **Any model but `gemini-3.5-flash-lite`**, and a stronger or independent judge. The judge is the same model family as the system under test; other models returned 503 during the run. | Self-preference and model-specific quirks (the `ActionInput` spelling was one) are unmeasured. | The same suite on a second model. |
| A13 | **Language and format.** English only; one corpus of 7 documents (markdown, HTML, PDF text); no scanned documents, no other languages. | | A corpus in another format/language. |

### B. Measured, but too weakly to lean on

| # | What | Weakness |
|---|---|---|
| B1 | **Run-to-run variance.** | One run per case. v2 → v3 → v3b (35 → 32 → 33 of 36) is within what one run each can produce; the judge's verdicts flipped in 5 of 100 repeated cells. |
| B2 | **Incomplete packets.** Token-budget stops (taxonomy R4). | 6 of 36 final runs stopped on the budget and **5 of those 6 passed every assertion**; the suite cannot tell an unfinished packet from a finished one. |
| B3 | **Straddle cases end to end.** | 5 claims, one run each; without the filter only 3 of 5 cited future wording, so "5 of 5 red before" is not literally true. The retrieval-level version (8 topics) is deterministic but is retrieval, not decisions. |
| B4 | **Cost of the date filter.** | 22 control questions I wrote myself (15 before running any retrieval); 0 of ~29 hits lost gives an upper bound near 11%, not "no cost". |
| B5 | **Judge validation.** | Only 3 of 70 outputs are wrong, so raw agreement ≈ the always-GROUNDED baseline (κ 0.4–0.6); labels are mine, not independent; planted errors are errors I thought of. |
| B6 | **Lapsed or not-yet-started policies.** | 2 of 36 cases; one PII case; no case with several policies or renewals. |
| B7 | **Severity.** | Failures are counted, not weighted by what a wrong answer would cost on a real claim. |

### C. Measured only on an older version of the system

| # | What | Measured on | Current state |
|---|---|---|---|
| C1 | Hand-read taxonomy (7 modes, frequencies) | v1 and v2 runs | not repeated on `triage-v3` / v3b |
| C2 | Judge agreement with hand labels | v1 and v2 outputs | not repeated; new outputs unlabelled |
| C3 | End-to-end straddle ablation (filter on/off) | legacy index, `triage-v2` | not repeated (quota; one run per cell) |
| C4 | MCP load probe, log size per claim | earlier system | not repeated |
| C5 | Whether `structured` chunking changes judged groundedness | — | no before/after on judged outputs |

**What this means for the headline.** 33/36 is a statement about *this* 36-claim synthetic set under these 9 assertions. It says nothing about A1–A13, and B2 means it overstates how many
packets finished.

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

Same 36 claims, same assertions, same model (`gemini-3.5-flash-lite`), one run per case. `eval/capstone_results_v3.json` (v3) and `eval/capstone_results_v3b.json` (v3b). The v3b run was split across two sessions: 10 claims, an interruption by the model quota (whose no-reply rows were discarded), then the remaining 26.

| | v1 (corrected) | v2 | v3 (before parser fix) | **v3b (current, parser fix)** |
|---|---|---|---|---|
| every assertion | 26/36 = 72% | 35/36 = 97% | 32/36 = 89% | **33/36 = 92%** |
| `citations_in_force` | 36/36 | 35/36 | 34/36 | 36/36 |
| `superseded_not_cited` | 28/36 | 36/36 | 35/36 | 34/36 |
| `numbers_distinct_and_correct` | 32/36 | 36/36 | 35/36 | 35/36 |
| completed with a Final Answer | 31/36 | 34/36 | 31/36 | 30/36 |
| stopped on a budget | 5 | 2 | 5 | **6** |
| tokens per claim, median / p90 | – | 20,962 / 27,367 | 28,284 / 32,758 | **27,266 / 32,997** |
| cost per claim | $0.0038 | $0.0036 | $0.0044 | $0.0044 |
| model attempted an outcome statement | 28 (13 cases) | 22 (13 cases) | 44 (20 cases) | **39 (19 cases)** |
| trajectory: clean route · tool-choice accuracy | 17/36 · 90.5% | 31/36 · 97.3% | 24/36 · 94.9% | 21/36 · 93.1% |

**v2 → v3 is a drop of 3 cases on n = 36, one run each — not distinguishable from run-to-run variance.** It is reported as it is. The four failures:

| claim | what happened | cause |
|---|---|---|
| CLM-2026-00606 | token budget exceeded (31.6k > 30k) → empty packet | **the gate** (one blocked referral + an extra "What is not covered" search, whose chunks ride in every later lap) |
| CLM-2026-00607 | token budget exceeded (36.4k) → empty packet | **the gate** (searched the section first, then the co-payment clause) |
| CLM-2026-00567 | 12 laps, 8 of them `malformed`: the model wrote `ActionInput:` (no space) so the parser rejected it | **not this change** — a brittle parser (SEAMS S22), **since fixed**: re-run once, it passes in 6 laps / 16.5k tokens. In the full v3b re-run it passes (see below). | |
| CLM-2026-00584 | cites `PW-HEALTH-002` clause 8 next to the endorsement that amends it | **not this change** — the S17 amendment-map gap (clause 8 is one of the 5 the map misses); v2 passed by variance |

**What the change did on the exclusion claims** (00509, 00514, 00567, 00561, 00442): the old prompt's phrases are gone — **0 of 62** logged queries quote them (v2: 4 of 89) —
and the model now writes its own ("alcohol intoxication under the influence", "What is not covered alcohol liquor influence"). On 4 of the 5 the governing clause
was still shown **and** cited; the fifth is the 00567 parser loop above. The gate fired on 11 claims and 31 queries now name the section. So removing the hints did
not, in this run, break the exclusion claims — with one run each.

**Costs to take seriously.** (1) The median run now uses 28.3k of a 30k token budget — the budget binds, which is what turned two gate-driven extra searches into empty
packets; either the budget, or the habit of resending every retrieved chunk on every lap (95% of tokens are prompt), has to change before this scales (see 10X_PLAN.md).
(2) The model tried to state an outcome **twice as often** (44 vs 22) once it could see the full exclusion list; the guard replaced all of them, so none shipped, but
"the guard's 0 is by construction" matters more now. (3) The gate can add a lap or a stall; it does not make the model's reasoning better, it makes the evidence reach it.

### 10b. v3b — the full re-run with the parser fix (33/36 = 92%)

`ActionInput:` now parses (SEAMS.md S22). **5 claims changed result against v3; net +1, which is within single-run noise:**

| claim | v3 | v3b | what it is |
|---|---|---|---|
| 00567, 00606, 00607 | fail | **pass** | 00567 was the `ActionInput` loop; 00606 and 00607 were token-budget stops that did not repeat |
| 00468 | pass | **fail** | token budget ran out before `get_limits` → no numbers (it was just over the limit in an earlier partial run too: 30,296) |
| 00491 | pass | **fail** | cites `PW-MOTOR-001` clause 4 beside the endorsement that amends it — the S17 map gap (clause 4 is one of the 5 the map misses) |

The three failing in v3b: **00468** (budget), **00491** and **00584** (both S17). So the remaining defects are the two known ones, not new ones.

**What the 33/36 hides.** 6 claims stopped on the token budget (00468, 00479, 00483, 00502, 00533, 00548) — and **5 of those 6 still passed every assertion**, because a forced
referral with some citations satisfies them. The assertions do not see an empty or partial packet (taxonomy mode R4). So "33/36" understates the budget problem: 6 of 36 runs
did not finish their own reasoning. The model also attempted an outcome statement 39 times (19 cases), the guard replaced all of them, and 10 packets reach the adjuster with a
`[withheld …]` hole. The exclusions gate blocked 15 premature referrals. Median tokens per claim are 27.3k against the 30k budget; the 90th percentile (33.0k) is over it.

**The headline number, on the final system.** The wrong-version citation rate (§1: 8/36 → 0/36) is **2/36 = 6% in v3b** (95% interval ≈ 2–18%): 00491 and 00584, both the S17 amendment-map gap. It moved a long way and did not stay at zero.

**How to read it.** v3b sits between v3 (89%) and v2 (97%) with no difference larger than run-to-run variance, and v2 was measured with the prompt that quoted exclusion
wording, so it is not a like-for-like target. The solid findings are: the parser loop is gone, and what is left is the token budget (S23) and the S17 amendment map.

**Still not repeated on v3/v3b:** the hand-read taxonomy and the judge validation. The numbers in §§1–8 are v1/v2 results and stay valid as that.
