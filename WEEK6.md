# Week 6 — validating the claim-summary judge

The eval prints a quality score for every claim summary. Nobody had ever checked that score
against a human. This week the check happened, and the honest answer is that the judge is
worse than its headline number suggests — not because it is badly written, but because one of
the two things it was being asked to detect is invisible from where it sits.

**The one command:**

```bash
python eval/run_evalset.py --judge v1
```

---

## The numbers, up front

| | |
|---|---|
| Eval cases | **27**, each tagged with one Week-5 taxonomy mode |
| Regression cases replayed from real failed traces | **2** (`tr_eeff25a3bea3`, `tr_297f38675314`) |
| Deterministic assertions | **5** |
| Judged criteria | **1** (binary) |
| Judged criteria in the version this replaced | 5, scored 1-10, never validated |
| **agreement_before** (judge_v1, first run) | **88.0%** (22/25) |
| **agreement_after** (judge_v2, first run) | **84.0%** (21/25) |
| judge_v1 over 3 runs | 88%, 84%, 75% → mean **82.3%** |
| judge_v2 over 3 runs | 84%, 84%, 88% → mean **85.3%** |
| always-GROUNDED baseline on this label set | **80.0%** |
| Verdicts unstable across 7 runs at temperature 0 | **7 of 25** |
| Known-ungrounded summaries caught: judge alone | **2 of 5** |
| Known-ungrounded summaries caught: judge + the new assertion | **4 of 5** |

The two numbers the brief asks for are 88.0% → 84.0%. The three-run means are 82.3% → 85.3%.
Both are reported because **neither difference is larger than this eval's noise floor**, and
saying so is the actual finding of the week. §5 has the measurement.

---

## 1. What is being scored

The app gained a second path this week: `src/summariser.py` reads an adjuster's claim file and
writes an eight-line summary with a coverage position on it.

```
Claim number: CLM-2026-00572
Date of loss: 2026-07-21
Line: motor
Policy: PW-MOTOR-001, END-2026-01
Position: PAYABLE
Deductible: INR 3,000
Exclusion relied on: none
Basis: A compulsory deductible of INR 3,000 applies to every own damage claim for vehicles
above 1500cc [2]. This endorsement updates the previous amount of INR 2,000 stated in the
base policy [1, 2].
```

The shape is fixed, and that is a scoring decision rather than a formatting one: a fixed shape
is what lets a regex decide most of the quality criteria. Free prose would have forced every
criterion through the judge.

## 2. The eval set — 27 cases, tagged by mode

`eval/claim_cases.yaml`. Every case is a claim file; the `mode` tag is the Week-5 failure it
was built to provoke, so the pass rate reports per mode. Reporting one average would let the
six condition cases and the controls hold the number up while a mode collapsed underneath.

| mode | n | what it probes |
|---|---|---|
| `refuses-answer-present` | 5 | refuses although the answering clause was retrieved |
| `drops-limiting-condition` | 6 | right figure, the condition that limits it dropped |
| `wrong-document-retrieved` | 5 | the clause exists and never reaches the list |
| `placeholder-banner-cited` | 3 | the corpus's own front matter served as a source |
| `pdf-table-mangled` | 3 | a PDF table arriving as one-line pseudo-headings |
| `clean-baseline` | 5 | controls — a change that breaks working behaviour shows up here |

There are deliberately **no gold answers in this file**. The judged criterion is validated
against hand labels written from the produced summaries, and an expected verdict sitting in
the case file would be a hint to the labeller.

**The two regression cases** are replayed from real failed traces in `traces/traces.jsonl`.
The `verbatim` field carries the exact query string that failed, copied from the trace, and it
is reproduced unchanged as the case's Coverage question line. Since this eval scores summaries
rather than answers, the verbatim question is wrapped in a claim file — that wrapping is the
only thing added.

| case | from trace | Week-5 failure | now |
|---|---|---|---|
| `m1-permanent-exclusions` | `tr_eeff25a3bea3` | refused with five exclusion clauses on screen | answers, cites Code-Excl04, correctly denies |
| `m3-waiting-period-comparison` | `tr_297f38675314` | refused; right table scored 0.0007 | answers — and now **pays a claim it should not** |

The second one is worth sitting with. The Week-5 failure is gone and a worse one replaced it:
it computes that a 12-month waiting period is satisfied when cover ran 2025-09-01 to
2026-08-01, which is 11 months. A refusal became a wrongful payment. That is exactly what a
regression test is for, and it only exists because the trace was kept.

## 3. Moving criteria out of the judge

`eval/judge_v0.txt` is the judge this replaced: five criteria, all judged by the model,
collapsed into a 1-10 score. Four of the five are decidable by a rule:

| judge_v0 criterion | now | why |
|---|---|---|
| 1. claim number in CLM-YYYY-NNNNN form | `assert_claim_number` | a regex, and it also checks the number is *this* claim's |
| 2. date of loss present and parseable | `assert_date_of_loss` | `strptime` over 7 formats, and rejects future dates |
| 3. excess/deductible numeric | `assert_deductible_numeric` | a currency regex, with explicit "none" allowed |
| 4. exclusion clause id cited on a denial | `assert_exclusion_cited_on_denial` | clause-id regex **plus** the cited document must be one actually retrieved |
| 5. position and figures follow from the passages | **stays judged** | needs reading comprehension across two documents |

All four were deleted from the prompt — diff `judge_v0.txt` against `judge_v1.txt`. A fifth
assertion was added later, driven by evidence rather than taste; §6.

**Count: 5 deterministic assertions, 1 judged criterion.**

The judged criterion is a **binary**, not a 1-10 score, and that was forced by the validation
plan. A 1-10 score cannot be validated against a human without a tolerance, and any tolerance
wide enough to be fair ("within 1") inflates agreement into meaninglessness. Nobody can tell a
6 from a 7 — not the model, and not me.

## 4. The blind protocol

The ordering is in git, not in a claim:

| commit | contains | does not contain |
|---|---|---|
| `0e1302c` | `labels_25.json`, the 27 cases, the summaries, judge_v0/v1, the assertions | any judge output — `eval/results.json` and `eval/agreement_*.json` do not exist in this tree |
| `7457812` | `eval/agreement_v1.json`, `prediction.txt` | `eval/judge_v2.txt` does not exist in this tree |

```bash
git show 0e1302c --stat          # labels land, no judge output
git show 7457812 --stat          # v1 measured and prediction filed, no judge_v2
```

25 labels, on 25 of the 27 cases, drawn by `random.Random(20260826).sample(sorted(case_ids), 25)`
— drawn rather than hand-picked so the labelled subset cannot quietly be the 25 that were
easiest to call. Labelled by reading each summary beside its retrieved passage text
(`eval/read_summary.py`, which has no flag to show a verdict because the file it would read did
not exist yet).

`labels_25.json` records the six tie-break rules (R1-R6) that were settled **before**
labelling — position counts as a claim, REFERRED is always groundable, incompleteness is not
ungroundedness, and so on. Without them the labels would have been arbitrary, and stating them
afterwards would have been indistinguishable from fitting them to the judge.

**Label distribution: 20 GROUNDED / 5 UNGROUNDED.** So a judge that answered GROUNDED
unconditionally would score 80%. That baseline is printed next to every agreement figure,
because 88% next to an 80% baseline is a very different claim from 88% on its own.

## 5. Agreement, and the noise floor

judge_v1, first run: **22/25 = 88.0%**. All three misses ran the same way — judge GROUNDED,
human UNGROUNDED. The lenient direction is the dangerous one: it waves invented coverage
through.

Then judge_v2, built with two of judge_v1's own disagreements as worked few-shot examples
(`cb-reimbursement-window` for superseded-as-current, `m1-room-rent-capping` for an exception
applied to facts it does not cover), with `m1-direct-hospital-payment` held out as the test of
generalisation.

judge_v2, first run: **21/25 = 84.0%**. It went down.

| | fixed | broke | held-out case |
|---|---|---|---|
| v1 → v2 | `m1-room-rent-capping` | `m2-ncb-protection`, `m2-nil-dep-third-claim` | `m1-direct-hospital-payment` — still missed |

Both breakages were the same misreading: v2 took "a benefit does not apply" to mean "the claim
is not payable", and flagged two summaries that correctly said a claim was payable while
explaining that the No Claim Bonus or Nil Depreciation benefit was lost. judge_v3 fixed exactly
that, plus tightened the currency check that v2 had satisfied with irrelevant passages, and
scored **88.0%** — v1's number again, with a different error set.

At which point the obvious question: **is a 4-point difference on 25 cases even real?**

It is not. Running the *same* prompt on the *same* summaries at temperature 0:

| judge | run 1 | run 2 | run 3 | mean | range |
|---|---|---|---|---|---|
| v1 | 88% | 84% | 75% | **82.3%** | 75–88% |
| v2 | 84% | 84% | 88% | **85.3%** | 84–88% |
| v3 | 88% | — | — | 88.0% | — |

**7 of the 25 verdicts were unstable across 7 runs**, at temperature 0:

```
cb-reimbursement-window        6x GROUNDED / 1x UNGROUNDED
cb-treatment-outside-india     6x GROUNDED / 1x UNGROUNDED
m1-room-rent-capping           3x GROUNDED / 4x UNGROUNDED
m2-ncb-protection              2x GROUNDED / 5x UNGROUNDED
m2-nil-dep-third-claim         4x GROUNDED / 3x UNGROUNDED
m3-cataract-sublimit           6x GROUNDED / 0x UNGROUNDED (1 run errored)
m3-waiting-period-comparison   2x GROUNDED / 5x UNGROUNDED
```

One flipped verdict on 25 cases is 4.0 percentage points. So the headline 88.0% → 84.0% is one
coin flip, and v1's own runs span 13 points. The three-run means (82.3% → 85.3%) put v2
nominally ahead, on ranges that almost entirely overlap.

**Consequence, stated plainly:** no prompt iteration measured on a single 25-case run can be
trusted on this eval, mine included. Either the set has to grow or every version has to be run
several times and reported as a mean. Both agreement figures above are quoted with that caveat
attached rather than as achievements.

## 6. What actually moved a number

Three prompts in a row failed to catch two particular summaries. Both quote a 2025 figure
accurately and present it as operative when a 2026 endorsement had changed it:

* `cb-reimbursement-window` — denies a claim on a 15-day submission window that an endorsement
  had extended to 30 days. The claim arrived on day 27. **A wrongly denied claim.**
* `m1-direct-hospital-payment` — gives a 6-hour pre-authorisation response time that an
  endorsement had reduced to 4.

This is not a weak prompt. It is an impossible question: **the amending clause was never
retrieved, so it is not in the judge's context**, and no instruction can conjure it. Asked to
reason about currency anyway, the judge invented justifications — v2 declared the 15-day window
"confirmed as operative by passage [3] and passage [5]", which are about document reminders and
digital submission and say nothing about the window.

Meanwhile the corpus front matter has carried a `supersedes` field the whole time. So the
question three model prompts got wrong is a dictionary lookup:

```
assert_currency_declared  (A5)
  relied_on := documents on the Policy line + documents behind the cited passages
  for each D in relied_on:
      for each (E, eff) where E supersedes D:
          if eff <= date_of_loss and E is not named anywhere in the summary:  FAIL
```

| | catches, of the 5 known-ungrounded summaries | false alarms on the 20 known-grounded | variance |
|---|---|---|---|
| judge_v1 alone | 2 | 0–1 depending on the run | 7/25 verdicts unstable |
| A5 alone | 2 | **0** | none — it is a lookup |
| judge_v1 + A5 | **4** | 0 | judge's share only |

That is the number that moved, and it moved because measurement pointed at it: **2 of 5 → 4 of
5**, at zero marginal cost and zero variance. The Week-6 lesson applied a second time, and the
second time driven by evidence rather than by taste. The remaining miss is
`m3-waiting-period-comparison`, the 11-versus-12-months arithmetic error, which is neither a
currency problem nor an unsupported quotation — a third class, and next week's problem.

## 7. Pass rate by mode

`python eval/run_evalset.py --judge v1`, 5 assertions and 1 judged criterion over 27 cases:

```
  mode                           n    assertions        judged       overall
  ---------------------------- ---  ------------  ------------  ------------
  clean-baseline                 5  4/5 =  80%     4/5 = 80%  3/5 =  60%
  drops-limiting-condition       6  6/6 = 100%    6/6 = 100%  6/6 = 100%
  pdf-table-mangled              3  3/3 = 100%    3/3 = 100%  3/3 = 100%
  placeholder-banner-cited       3  3/3 = 100%    3/3 = 100%  3/3 = 100%
  refuses-answer-present         5  4/5 =  80%    5/5 = 100%  4/5 =  80%
  wrong-document-retrieved       5  5/5 = 100%    5/5 = 100%  5/5 = 100%
  ---------------------------- ---  ------------  ------------  ------------
  TOTAL                         27  25/27 =  93%   26/27 = 96%  24/27 =  89%

  ASSERTION BREAKDOWN (deterministic, no model involved)
    claim_number_format          27/27 = 100%
    date_of_loss_parseable       27/27 = 100%
    deductible_numeric           27/27 = 100%
    exclusion_cited_on_denial    27/27 = 100%
    currency_declared            25/27 =  93%
    citations_resolve            25/27 =  93%   (pre-existing check)
```

Read the per-mode column, not the total. **`clean-baseline` is the worst mode at 60%** — the
controls, the cases that are supposed to be easy. Both failures are there:
`cb-reimbursement-window` fails `currency_declared`, and `cb-tyres-only` says a tyre-only loss
is PAYABLE when the policy excludes it. The 89% total hides that completely, and the four modes
built to provoke Week-5 failures all score 100%, which mostly says the cases were aimed at
failures the app has since stopped making.

## 8. Two disagreements, and who was right

**`cb-reimbursement-window` — the human was right.** The judge said GROUNDED because the
15-day window is quoted exactly from passage [1] and the arithmetic is correct. It is, and the
summary still denies a claim that should be paid, because an endorsement had extended the
window to 30 days before this date of loss. The judge could not have known: that endorsement
was not among the five passages it was shown. Right about the text, wrong about the claim. This
one is now caught deterministically by A5 and no longer asked of the judge.

**`m1-room-rent-capping` — the human was right about the claim, the judge was arguably right
about the prompt.** The summary says PAYABLE for a deluxe room bill while the retrieved passage
limits the entitlement to a standard A/C room, and leans on a proportionate-deduction exception
whose precondition — a hospital that does not do differential billing — appears nowhere in the
claim file. My label was UNGROUNDED on rule R1, that a position is itself a claim needing
support. The judge said GROUNDED, and on the literal text of `judge_v1.txt` it had a case:
every sentence *is* supported by a passage. R1 was written down in `labels_25.json` and never
made it into the prompt clearly enough. That is a defect in my prompt, not only in the judge's
reading, and it is why v2's worked example fixed this case immediately.

**`m2-ncb-protection` — the judge was wrong, in v2 only.** v2 called it UNGROUNDED because the
summary says PAYABLE while stating that a second claim reverts the No Claim Bonus to nil. Those
are two compatible facts: the claim is payable, the bonus is gone. v2 had been taught to check
that a rule fits the facts and over-applied it. v3 says so explicitly and the case came back.

## 9. Scoring the prediction

`prediction.txt`, committed at `7457812` before `judge_v2.txt` existed:

> Showing judge_v2 the cb-reimbursement-window and m1-room-rent-capping disagreements as
> few-shot examples will fix those two and generalise to the unseen m1-direct-hospital-payment
> case, taking agreement from 88.0% (22/25) to 100% (25/25) with no new false-UNGROUNDED
> verdicts on the 20 cases the judge already got right.

**Wrong in every measurable part.**

| predicted | actual |
|---|---|
| both taught cases fixed | 1 of 2 — `m1-room-rent-capping` fixed, `cb-reimbursement-window` not |
| generalises to the held-out case | it did not; `m1-direct-hospital-payment` stayed GROUNDED |
| 88.0% → 100% | 88.0% → 84.0%; agreement went **down** |
| no new false-UNGROUNDED | two: `m2-ncb-protection`, `m2-nil-dep-third-claim` |

All three of the failure conditions I had written down in advance triggered, including the one
I called most likely (over-correction into false alarms). Writing them down is the only reason
the scoring above is a checkable table rather than a paragraph of reinterpretation.

The part I got wrong that I had not even listed as a risk is the more useful one: **I predicted
that a prompt could fix a class the judge structurally cannot see.** The supersession cases
were never a prompting problem. Three prompts, three failures, and the fix turned out to be
nine lines of metadata lookup. I also assumed a 4-point move would mean something on 25 cases,
which §5 shows it does not.

## 10. Bonus — RAGAS faithfulness and context precision

`python eval/ragas_metrics.py`. Faithfulness the RAGAS way (decompose the summary into atomic
claims, verify each against the retrieved passages) and context precision as rank-weighted
mean precision@k.

```
  mean faithfulness        1.000   over 27 cases
  mean context precision   0.738   over 27 cases
```

**Mean faithfulness is 1.000. Every claim in every summary is supported by the passages it was
given. The model invents nothing — and that is not the same as being right.**

The case the brief asks for, confidently and faithfully wrong:

| case | faithfulness | context precision |
|---|---|---|
| **`cb-tyres-only`** | **1.00** | **0.00** |

Two tyres burst in a pothole and nothing else was damaged. All five retrieved passages came
from the motor *endorsement* END-2026-01 — Nil Depreciation, No Claim Bonus protection, the
deductible revision, digital survey, total loss threshold. Zero of the five bear on whether a
tyre-only loss is payable. The clause that decides it, `PW-MOTOR-001` Clause 3 — *"damage to
tyres and tubes unless the vehicle is damaged at the same time"* — is in the corpus and was
never retrieved. So the exclusions of the wrong document were in front of the model, it quoted
what it was given with perfect fidelity, and it said **PAYABLE** on a loss the policy excludes.

Six of 27 cases (22%) score faithfulness ≥ 0.90 with context precision ≤ 0.50, four of them at
context precision **0.00**:

```
  m3-motor-intimation-window     1.00   0.00   wrong-document-retrieved
  m3-motor-drink-driving         1.00   0.00   wrong-document-retrieved
  m4-what-does-this-cover        1.00   0.00   placeholder-banner-cited
  cb-tyres-only                  1.00   0.00   clean-baseline
  m2-settlement-timeline         1.00   0.20   drops-limiting-condition
  m4-which-document-governs      1.00   0.33   placeholder-banner-cited
```

**Why the average hides it.** Faithfulness has no variance to hide anything *in* — it is 1.000
everywhere, so as a monitoring signal it is dead. It would read 1.000 whether retrieval fetched
the governing exclusion or a page of boilerplate, because it only ever asks "did you make this
up", never "was this the right material". Context precision does move, and its mean of 0.738
sounds respectable while being built from 21 cases near 1.0 and four at exactly zero — the mean
of a bimodal distribution, sitting in a gap where no case actually lives. The four zeros are
the only cases that matter and the average is the one number guaranteed not to show them.

A small irony worth recording: the first version of the filter that surfaces these cases was
`(r["context_precision"] or 1) <= 0.5`, and `0.0 or 1` is `1` in Python, so it silently dropped
every case at exactly 0.00 — all four of the worst ones. A falsy-zero bug in the tool built to
stop averages hiding things. It is fixed, with a comment, in `eval/ragas_metrics.py`.

## 11. What this does not establish

* **The agreement figures are noisy.** 25 cases, 4 points per flipped verdict, 7 of 25
  verdicts unstable at temperature 0. Treat v1-versus-v2 as a tie.
* **judge_v3 was fitted to these 25 labels.** The labels never moved — `labels_25.json` is
  untouched since its own commit — but the prompt was edited twice against the same set, so
  some of v3's 88% may be memorisation. A held-out label set is needed to tell.
* **One labeller, no second opinion.** Where the judge and I disagreed I mostly concluded I was
  right; `m1-room-rent-capping` in §8 is the case where that is genuinely arguable.
* **The rules R1-R6 are mine.** Written before labelling and published, but a different
  reasonable reading of the criterion would move several labels, and with them the agreement.
* **RAGAS relevance judgements come from the same model family as the judge**, so context
  precision inherits some of the same blind spots.

## 12. Reproducing

```bash
python eval/make_summaries.py                       # regenerate the summaries
python eval/run_evalset.py --judge v1               # THE one command: pass rate by mode
python eval/validate_judge.py --judge v1            # agreement vs labels_25.json
python eval/validate_judge.py --judge v2            # the iteration
python eval/ragas_metrics.py                        # faithfulness + context precision
python eval/read_summary.py --ids cb-tyres-only     # read a summary with its passages
diff eval/judge_v1.txt eval/judge_v2.txt            # the two worked examples added
```
