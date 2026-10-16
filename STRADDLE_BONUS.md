# Bonus — loss-date-aware retrieval, proven; and what the date filter cost

**The brief:** make the retriever resolve the wording in force on the *loss* date — a filter the code enforces, not a hint in
the prompt; add cases that straddle an endorsement, including one dated the day before it took effect; show them red before
and green after; then report what the filter cost in hit@3 on cases that do **not** straddle a boundary.

**The filter:** `in_force_hits()` in `src/retriever.py` drops, after fusion and before rerank, any chunk whose `effective_date`
is later than the loss date or whose line of business is neither the claim's product nor `all`. The agent cannot skip it:
the host overwrites `loss_date` and `product` on every `search_wording` call. Corpus endorsements are dated 2026, not 2025;
`END-2026-01` (motor) takes effect 2026-04-01 and `END-2026-02` (health) 2026-05-01.

## 1. Straddle cases, retrieval level (deterministic, no model) — `eval/straddle_bonus.py`

Eight amended clauses, each asked with a loss dated **the day before** the endorsement. *clean@3* = the in-force clause is in
the top 3 **and** no chunk from a not-yet-in-force document is (the agent reads all three, so this is the primary measure).

| amended clause | no filter: clean@3 · rank-1 | with filter: clean@3 · rank-1 |
|---|---|---|
| motor deductible | RED · wrong version | GREEN · right |
| motor constructive-total-loss threshold | RED · wrong | GREEN · right |
| motor intimation window | GREEN · right | GREEN · right |
| motor reimbursement window | RED · right | GREEN · right |
| health co-payment | RED · wrong | GREEN · right |
| health reimbursement window | RED · wrong | GREEN · right |
| health pre/post-hospitalisation | RED · wrong | GREEN · other |
| health initial waiting period | RED · wrong | GREEN · other |
| **red** | **7 / 8** (6/8 wrong at rank 1) | **0 / 8** (0/8 wrong at rank 1) |

Two honest notes. **Rank-1 is right in 6 of 8 with the filter, not 8:** in the two "other" rows the in-force clause is at
rank 2 (another base clause ranks first once the endorsement chunk is gone) — not red, but not first either. And the eight were
written before the check was first run, so the 7 red were not picked after the fact; one topic (motor intimation) was green
without the filter simply because of how it ranked.

**Effective-day cases (loss ON the day the endorsement starts) are not fixed by this filter, and cannot be:** both versions are in
force that day, so nothing is out of force to drop. 2/8 stay red at rank 1 with or without it (motor intimation, motor
reimbursement). That needs the superseded-clause marker (S12), whose amendment map is itself missing 5 of 16 amended clauses —
including exactly those two (`SEAMS.md` S17, found during this bonus).

## 2. Straddle cases, end to end (the agent, same claims, filter ON vs OFF) — `eval/run_straddle_ablation.py`

**These runs used the legacy `recursive` index and the `triage-v2` prompt — before the capstone moved to `structured` chunking and `triage-v3` (SEAMS.md S21). They have not been repeated; the filter's mechanism does not depend on chunking, but the numbers are for that configuration.** OFF = `WORDING_DATE_FILTER=off` in the wording server; everything else identical (prompt, model, claims server, marker). Five
claims whose loss **precedes** an endorsement that restates or amends the clause asked about, one control on the effective day.
**Definitions were written in the script's header before any run.** *Exposed* = the model was shown a chunk from a document not yet
in force. *Red* = the packet **cites** one.

| claim | loss date | OFF: exposed | OFF: cites future wording | ON: exposed | ON: cites |
|---|---|---|---|---|---|
| 00601 deductible | 2026-03-31 | END-2026-01 | **RED** (END-2026-01) | – | green |
| 00607 co-payment | 2026-04-30 | END-2026-02 | **RED** (END-2026-02) | – | green |
| 00442 non-medical items | 2026-02-27 | END-2026-02 | **RED** (END-2026-02) | – | green |
| 00609 room rent | 2026-04-30 | END-2026-02 | green | – | green |
| 00437 room rent | 2026-03-19 | END-2026-02 | green | – | green |
| 00602 control (effective day) | 2026-04-01 | – | green | – | green |

| | exposed to out-of-force wording | cites it (red) | passes every assertion |
|---|---|---|---|
| filter **OFF**, 5 before-endorsement claims | **5 / 5** | **3 / 5** | 2 / 5 |
| filter **ON**, same 5 | **0 / 5** | **0 / 5** | 5 / 5 |

**"All 5 red before" is not literally true end to end.** Without the filter every one of the 5 was *shown* wording that did not
yet exist (that is deterministic — it is what the filter removes), but only 3 of the 5 *cited* it; in the other two the model
resisted. So: 5/5 exposed → 0/5 with the filter (mechanism, solid); 3/5 red → 0/5 (a sample of a stochastic system).

**Limits.** **One run per cell.** I planned two; the Gemini quota ran out partway through the second round (429s), and those runs
are set aside (`straddle_ablation_raw_with_outage.json`), as is the second control, CLM-2026-00608, whose pair was cut off.
n=5 claims, so "3/5" has a wide interval. The control shows no difference, but it is a single pair.

## 3. What the filter cost — hit@3 on cases that do NOT straddle

22 control questions whose answer is in a clause **no endorsement amends**: the 7 `answerable` ones in `eval/questions.yaml` and
15 more in `eval/questions_straddle_control.yaml`, which I wrote from the corpus text **before running any retrieval on them**.
Each asked at three loss dates (before every endorsement / only END-2026-01 in force / after all), and under both products where
the answering document applies to every line — 31 trials per date.

| loss date | baseline hit@3 | with filter hit@3 | lost | gained | rank-1 chunk unchanged |
|---|---|---|---|---|---|
| 2026-03-31 (before every endorsement) | 29 / 31 | 31 / 31 | **0** | 2 | 25 / 31 |
| 2026-04-15 (only END-2026-01 in force) | 29 / 31 | 31 / 31 | **0** | 2 | 26 / 31 |
| 2026-07-01 (after every endorsement) | 29 / 31 | 30 / 31 | **0** | 1 | 30 / 31 |

*Measured twice.* The first run (legacy `recursive` index) had baseline 30/31 and gained 1; this table is the re-run after the capstone moved to the
`structured` index (SEAMS.md S21). **Scoped hit@3 is identical on both indexes (31/31, 31/31, 30/31); the unscoped baseline got slightly worse on
the new one** (`tyre-limit` now misses without the filter: its bullet sits in a larger chunk). The straddle table in §1 is also unchanged on the new index
(7/8 red → 0/8; effective-day still 2/8).

**I found no hit@3 cost.** 0 of 29 baseline hits were lost; with ~30 trials the 95% upper bound on a loss rate is about 11%, so "no
detectable cost" is the claim, not "no cost". The changes are *gains*: `motor-survey` and `tyre-limit` are missed without the filter and found with it. What the filter did change is ranking: **5 of 31 trials (16%) have a different
rank-1 chunk** at the pre-endorsement date, without losing the answer. Latency did not get worse — p50 323 ms with the filter vs
787 ms without (alternating order, warmed up, 24 calls), because fewer candidates reach the reranker.

**Costs that are real but not hit@3:**
- It is only as good as the metadata: an undated chunk is kept (`undated_kept` is reported), and a wrong `effective_date` or
  `line_of_business` silently drops the right clause.
- A loss dated before the base wording took effect returns nothing in force — by design, and loudly (`gate: "date"`), but it is a
  refusal where the unscoped retriever would have answered with something.
- It does nothing for superseded-but-in-force wording (§1) — a different mechanism.
- A question whose only answer is a *new* endorsement clause becomes unanswerable for a loss before it took effect. That is the
  filter working, and is deliberately outside the control set.

**Caveats on the cost number:** the 15 new questions are mine; n=22 questions is small; the unscoped baseline already misses 2 of 22.

## 4. Permanent guards

`tests/test_straddle_cases.py` (5 tests, need the index): at least 5 day-before cases are red without the loss date (so "green
after" can discriminate); every day-before case is clean with it; no wrong version at rank 1; the filter loses no hit@3 on the
control questions; and the ablation switch defaults to filter-on.
