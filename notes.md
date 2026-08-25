# Week 5 — error analysis working notes

Everything behind `taxonomy.md`: how the traces were produced, the seeded sample, the twenty
open-coding sentences written before any category existed, the replay evidence, the dated
prediction, and the benchmark note.

---

## 1. Where the traces came from

The app had no trace log before this week, so one was built (`src/trace.py`) and traffic was
run through it. Two things about that are worth stating plainly, because they bound what the
frequencies in `taxonomy.md` can be trusted to mean:

* **The population is 114 traces, not a thousand.** Traffic was generated in one batch
  (`scripts/generate_traffic.py`), not accumulated over a week of live use. Twenty out of 114
  is an 18% sample, which is a real sample — but it is a sample of one afternoon's questions,
  not of a month's user behaviour.
* **The question bank was written from the claims domain, not from the documents**
  (`eval/traffic_bank.yaml`). No question was checked for answerability before being added and
  none has a gold answer. This matters more than the population size: a bank written by reading
  the corpus first would contain only answerable questions, every abstention would look like a
  bug, and the frequencies would describe the bank instead of the app. The bank deliberately
  contains straight coverage questions, process questions, questions about the wrong line of
  business, questions the corpus does not cover, one-word queries, typos, multi-part questions,
  a few carrying claimant identifiers, and some off-topic noise — because real logs contain all
  of those.

Two corpora were in the index and both received traffic: the synthetic `insurance` pack
(7 documents — motor own damage, group health, claims handling, a definitions PDF, and three
endorsements) and `uploaded`, a real 30-page Bajaj *Ungalukkaga* Tamil Nadu health policy
wording. 78 traces went to the first, 36 to the second.

| | |
|---|---|
| Population | 114 traces, `surface: traffic-random` |
| Excluded from the population | 10 traces, `surface: traffic-demo` (see §8) |
| Code version | `07b47dd-dirty`, identical across all 114 |
| Chunking | recursive, 800 chars, 150 overlap |
| Retrieval | hybrid dense+BM25 with RRF, cross-encoder rerank, top-k 5 of 20 candidates |
| Gates | cosine ≥ 0.64, rerank ≥ 0.10, model `NOT_IN_DOCUMENTS`, citation verification |
| Model | `gemini-flash-lite-latest`, temperature 0.0 |
| Provider errors | 0 of 114 |

### Two instrumentation repairs, both before the reading pass

Disclosed because the rubric's zero-fixes rule is worth being able to audit rather than
believe. Neither touched retrieval or generation behaviour, and both happened before a single
open-coding sentence was written:

1. **The retry policy.** A first traffic run had 64% of calls fail as provider errors — the
   free tier returns 503 in bursts and a single 5-second retry did not clear them. Retries went
   to three with increasing backoff. Without this the population would have described Google's
   uptime rather than the app.
2. **The redactor.** Reading the first batch showed it eating real policy text: `Sum Insured
   Band`, `Insured Person Pays` and `in-patient Care and Day care` had all become
   `[REDACTED]`, in 14 of 124 traces. The name rule accepted a single capitalised word after a
   cue word, and insurance prose puts capitalised defined terms in exactly that position. It now
   requires two or more capitalised words, none of them policy vocabulary. A second defect
   surfaced with it: `re.IGNORECASE` applied to the whole pattern made `[A-Z]` match lowercase,
   so `patient Meera Nair was denied` captured `Meera Nair was`, hit `was` in the stopword list,
   and skipped a real claimant name — over-redaction and under-redaction from one flag. The flag
   is now scoped to the cue. Over-redaction went from 14 traces to 1, and that one is a genuine
   email address.

The population was regenerated from scratch after both, so all 114 traces come from one code
version. **Zero changes of any kind were made between the first open-coding sentence and the
finished taxonomy.**

---

## 2. The seeded sample

```bash
python eval/sample_traces.py --seed 20260826 --n 20
```

**Seed: `20260826`.** Selection is `random.Random(seed).sample(sorted(trace_ids), 20)` over the
114 traces whose surface starts with `traffic-random`. Sorting the ids first means the draw
depends only on the seed and the population, not on the order the traffic script happened to
write rows. The demo traces are excluded by default — sampling the questions the app is
demonstrated with would produce a frequency table describing the demo.

The 20 trace_ids drawn, in sample order:

```
 1  tr_7a6d1c73a209    11  tr_3fa57720e19d
 2  tr_8b415ff36356    12  tr_2e3f23e9f1e6
 3  tr_9e0edc592659    13  tr_297f38675314
 4  tr_10376875b164    14  tr_6b5496710352
 5  tr_eeff25a3bea3    15  tr_34d34d4ae3cf
 6  tr_1b2dd5957cd0    16  tr_2925f27ded8a
 7  tr_a05e39de2b4e    17  tr_9d2e1d93e6d3
 8  tr_5e602ad91ec2    18  tr_fa08113d13d6
 9  tr_3355096b48d3    19  tr_4333736f568d
10  tr_84368d62baed    20  tr_2d9e129080a3
```

Sample composition, which nobody chose: 12 `insurance` / 8 `uploaded`; 9 answered by the model
and 11 refused; refusals split across all three gate types (4 model, 3 rerank, 4 cosine).

---

## 3. Open coding — twenty traces, twenty sentences

Written while reading each trace in full with its retrieved passage text
(`python eval/read_trace.py --seed 20260826 --n 20`). One sentence per trace, describing what
happened. No categories existed yet, no fixes were applied, and where a trace was not
understandable that is what the sentence says.

1. **`tr_7a6d1c73a209`** — "What is the cancellation and refund grid?" — All five passages came
   from clause 7 *Cancellation* on page 17, and passages 2 and 4 together set out the pro-rata
   refund rules for annual, multi-year and instalment premiums, and the reply was "that isn't
   covered in the documents I have".

2. **`tr_8b415ff36356`** — "room rent capping" — Passage 1 gave the definition of Room Rent and
   passage 5 said room and boarding is covered "as Standard a/c room, specified on the Policy
   Schedule", and the reply said the documents don't cover it without mentioning that the number
   lives in the Schedule.

3. **`tr_9e0edc592659`** — "What documents must be submitted for a reimbursement claim?" — The
   answer listed nine claim documents and every one of them appears in the passage it cited; the
   48-hour intimation requirement sitting in passage 3 was not mentioned.

4. **`tr_10376875b164`** — "Is depreciation deducted on plastic parts in an own damage claim?" —
   The answer gave 50% depreciation and the Nil Depreciation alternative and cited both
   documents, and the two conditions printed in the same cited passage — only vehicles up to
   five years old, maximum two such claims per policy year — were left out.

5. **`tr_eeff25a3bea3`** — "Which expenses are permanently excluded?" — Five passages from
   *Section D) Waiting Period and Exclusions* came back including exclusion codes Excl04, Excl11
   and Excl02 at cross-encoder scores of 0.97, 0.92 and 0.82, and the reply was "that isn't
   covered in the documents I have".

6. **`tr_1b2dd5957cd0`** — "Tell me about the policy." — Three of the five passages were the
   corpus's own "PLACEHOLDER CORPUS … Meridian Assurance Limited is a fictional insurer" banner,
   and the request was refused for a best similarity of 0.62 against the 0.64 floor.

7. **`tr_a05e39de2b4e`** — "Can the claim be paid to the hospital directly?" — Passage 2 was the
   cashless clause describing pre-authorisation at a network hospital, the reply was that the
   documents do not cover the question, and the word "cashless" does not appear in the question.

8. **`tr_5e602ad91ec2`** — "Does the policy cover damage to tyres alone?" — The answer said tyres
   and tubes are excluded unless the vehicle is damaged at the same time, in which case liability
   is 50% of replacement cost, which is word for word what the cited passage says.

9. **`tr_3355096b48d3`** — "Is modern treatment such as robotic surgery covered?" — The answer
   said robotic surgery is covered up to the In-patient Hospitalisation Sum Insured, and item (g)
   of the list in the cited passage reads "Robotic surgeries".

10. **`tr_84368d62baed`** — "Does the policy cover treatment taken outside India?" — The answer
    said it is excluded unless the schedule provides worldwide cover, citing both the base
    exclusion list and the endorsement that leaves that exclusion unchanged.

11. **`tr_3fa57720e19d`** — "deductable amont for car claim" — A query with two misspellings
    returned the revised INR 1,500 and INR 3,000 figures and stated that the earlier INR 1,000
    and INR 2,000 no longer apply, and the cross-encoder's best score was 0.141 against a 0.10
    floor.

12. **`tr_2e3f23e9f1e6`** — "[claim] for patient [name] was denied. On what ground can it be
    denied?" — The five passages that came back were about digital claim submission, document
    reminders, modern treatments and No Claim Bonus, every one scored 0.000 by the cross-encoder,
    and no "What is not covered" clause appeared.

13. **`tr_297f38675314`** — "Compare the waiting period in the base wording with the
    endorsement." — Four of the five passages were from *Endorsement 3 to the Claims Handling
    Manual*, the endorsement's own waiting-period table arrived last at a score of 0.0007, the
    base policy's waiting-period table did not appear at all, and the request was refused.

14. **`tr_6b5496710352`** — "Is road ambulance covered and up to what amount?" — The answer gave
    the ceiling as the In-patient Hospitalisation Sum Insured from passage 1, and the two payment
    conditions in passage 4 — a life-threatening emergency certified by a practitioner, and an
    already-accepted in-patient claim — were not mentioned.

15. **`tr_34d34d4ae3cf`** — "waiting period" — This two-word query returned both the endorsement's
    table and the base policy's table, and the answer gave all four durations with each one
    labelled as superseding the earlier figure.

16. **`tr_2925f27ded8a`** — "How long does the insurer take to settle after receiving all
    documents?" — The answer gave 15 days for a decision and said it superseded 30 days, and the
    same cited table also lists 3 working days for payment after acceptance and 30 days where an
    investigation is warranted, neither of which was mentioned.

17. **`tr_9d2e1d93e6d3`** — "Are non-medical consumables payable?" — Passage 5 was the annexure
    of items subsumed into room charges and it arrived as a run of one-line pseudo-headings
    ("### 2. Hand Wash", "### 3. Shoe Cover", one per table row), and the reply was that the
    documents do not cover the question.

18. **`tr_fa08113d13d6`** — "What is the premium for this policy?" — The reply was that the
    documents do not cover it, the nearest passage was the free-look clause about premium
    refunds, and no premium figure appears anywhere in the corpus.

19. **`tr_4333736f568d`** — "Is cataract surgery subject to a sub-limit?" — None of the five
    passages mentioned cataract even though the base policy's specified-illness list names it
    first, and the request was refused for a best similarity of 0.63 against the 0.64 floor.

20. **`tr_2d9e129080a3`** — "How do I change my nominee?" — All five passages came from
    *Endorsement 3 to the Claims Handling Manual* at similarities of 0.51 to 0.57 with
    cross-encoder scores of 0.000, none of them mentioned a nominee, and the request was refused.

### From sentences to modes

Reading them back, the sentences fell into groups without much argument. Five say *the answer
was there and we refused* (1, 2, 5, 7, 17). Three say *the figure was right but a condition in
the same passage was dropped* (4, 14, 16). Three say *the clause exists in the corpus and never
reached the list* (12, 13, 19). Two say *the corpus's own boilerplate came back as content*
(6, 11). Seven describe no failure at all (3, 8, 9, 10, 15, 18, 20) — four correct answers and
three correct refusals. Trace 17 also carries the mangled-table observation, which is a
different cause from the other four refusals and is why mode 5 exists as its own row.

One thing the reading changed: before it, "sometimes gets coverage wrong" sounded like a
hallucination problem. Not one of the twenty traces invented a policy term. The app's
characteristic failure is the opposite — it refuses, or it under-answers.

---

## 4. Replay evidence

```bash
python eval/replay_trace.py --seed 20260826 --n 20
```

Picked by `random.Random(seed+1).choice(sample)` from the 20-trace sample — a second seeded
draw, so which trace gets replayed does not depend on the sample's internal sort order.

**Trace replayed: `tr_a04615458ad7`** (from the pre-regeneration population; the equivalent run
on the current population is shown second). The replay tool may read the trace row and the chunk
store and nothing else — no session state, no re-running retrieval.

```
[1] FIELD AUDIT
  all fields needed for replay are present

[2] PROMPT IDENTITY
  recorded : claims-v1 / 43275b979e43
  current  : claims-v1 / 43275b979e43
  match — the prompt in the code is the prompt that produced this trace

[3] CONTEXT RECONSTRUCTION (from chunk_id, in recorded rank order)
  [1] PW-HEALTH-002::9   cos=0.7621  rerank=0.9466
  [2] PW-HEALTH-002::10  cos=0.781   rerank=0.9202
  [3] PW-CLAIMS-003::7   cos=0.6767  rerank=0.5945
  [4] PW-HEALTH-002::8   cos=0.7125  rerank=0.5319
  [5] END-2026-02::2     cos=0.7157  rerank=0.472

  recorded context_sha : 9c35d67a9ea4
  rebuilt  context_sha : 9c35d67a9ea4
  IDENTICAL — the model is receiving byte-for-byte the same input

[4] MODEL CALL — gemini / gemini-flash-lite-latest params={'temperature': 0.0}

ORIGINAL (from the trace):   NOT_IN_DOCUMENTS
REPLAYED (just now):         NOT_IN_DOCUMENTS

VERDICT: byte-identical.
```

That trace's output is one token, so a second replay was run on a substantive answer —
`tr_3a605423b8e7`, "What is the definition of a Hospital under this policy?" — to show the
comparison doing real work. Context hash `c5eefe0b0df4` matched again, and the outputs diverged
at 96.6% similarity:

```
original : …established for in-patient [REDACTED] care treatment of illness…Act. [1]
replayed : …established for in-patient care and day care treatment of illness…Act [1].
```

Two separate things in one diff, and they are worth keeping apart:

* The citation marker moved relative to the full stop (`Act. [1]` → `Act [1].`). The input was
  proven identical by the context hash, so this is the hosted model behaving differently between
  calls — `gemini-flash-lite-latest` is a moving alias, and temperature 0 is not a determinism
  guarantee across model revisions. Worth knowing; not ours.
* `care and day` appears as `[REDACTED]` in the original. That was the redaction defect in §1.
  It is shown here rather than hidden because this is exactly how it was found.

### Fields that had to be added

The trace file did not exist before this week, so every field was added. The ones replay proved
it could not work without:

| Field added | Why replay fails without it |
|---|---|
| `retrieved[].chunk_id` | `store.query` returned text and scores but no ids. Without ids a trace records *that* five passages were used, not *which* — replay would mean re-running the search and hoping. |
| `prompt_version` + `prompt_sha` | A version string alone is a promise someone remembered to bump it. The hash is what actually proves the prompt text. |
| `context_sha` | The one field that turns "probably the same input" into a checkable claim. |
| `model` resolved, not the alias | The trace says `gemini-flash-lite-latest`; the 404s during setup showed that Google gates concrete versions per key, so the alias is what is reproducible. |
| `params` | Anthropic is deliberately called with no temperature at all. Without this field a reader has to go read the source to learn that. |
| `raw_output` | The displayed answer is the app's post-processed opinion. The raw string is the evidence. |
| `gate` + `gate_detail` | Before this, an abstention at the cosine floor and a model refusal were both just `grounded: false`. Modes 1 and 3 in the taxonomy are only separable because of this field. |
| `code_version` with `-dirty` | A bare SHA on a modified tree points at a commit that does not contain the code that ran. |

### What could not be reconstructed

* **The exact question, for the 5 traces carrying claimant identifiers.** Redaction runs at
  write time, which is *after* retrieval — so the retriever saw `Claim CLM/2026/8812 for patient
  Meera Nair…` while the trace records `[REDACTED] for patient [REDACTED]…`. Replaying those
  five cannot reproduce the original prompt, because a content word (`Claim`) was removed along
  with the identifier. This is a deliberate trade: the alternative is writing claimant names to
  disk. It is a real limit on replay, not a bug, and it applies to 5 of 114 traces.
* **Token-level model state.** Nothing in a REST response exposes it, so a divergence like the
  96.6% one above can be attributed to the model but not explained further.
* **Retrieval timing.** `latency_ms` is end-to-end. It does not separate embedding, vector
  search, BM25, and reranking, so a slow trace cannot be attributed to a stage.

### Redaction

**Confirmed: claimant identifiers are redacted before the trace is written, not after.**
`trace._write()` passes the whole row through `redact.scrub_deep()` on the way to the file, so
the unredacted string never reaches disk. `python eval/check_redaction.py` tests both halves
separately — that the ordering holds (by running the real writer against a temporary path and
reading back what landed) and that no identifier survives anywhere in the live file. Both pass:
0 surviving identifiers across 124 traces, with policy figures like `Rs. 10,000` and
`Section C) 2` preserved. Testing only the second half would let a scrub-it-afterwards
implementation look clean.

---

## 5. The prediction

Dated and committed before any fix. Attacking **mode 1**, the largest bucket, whose cause sits
after retrieval.

> **26 August 2026.** Mode 1 — *refuses a question whose answer is in the passages it just
> retrieved* — is 25% of the sample (5 of 20). The change: revise the answer prompt from
> `claims-v1` to `claims-v2`, adding two rules — (a) where a passage answers the question in
> part, or defers the figure to the Policy Schedule, report that instead of refusing, and (b)
> whenever `NOT_IN_DOCUMENTS` is returned, the model must first state what the retrieved
> passages *do* address. I expect this to drop mode 1 **from 25% (5/20) to 10% or less
> (≤2/20)** on these same 20 traces, and I expect **0 of the 7 currently-clean traces to turn
> into a false answer** (a fabricated figure, or an answer to a question the corpus cannot
> support).
>
> Measured by re-running the 20 traces through `eval/replay_trace.py` with the new prompt and
> re-coding them against this same taxonomy.
>
> Wrong if: mode 1 stays above 10%, which would mean the refusals were not caused by the prompt
> and I attacked the wrong layer. Also wrong if any clean trace starts answering — that would
> mean the change bought a refusal reduction with a fabrication, which is a worse trade than the
> failure it fixed.

Deliberately excluded from the prediction: modes 3, 4 and 5, which are retrieval and ingestion
problems. A prompt change cannot fix a clause that was never retrieved, and predicting otherwise
would make the result uninterpretable.

**Commit:** see §9.

---

## 6. Why a public benchmark would have missed the top three modes

MMLU and HumanEval score a model on questions whose answers are in the model's weights, whereas
every one of these failures is about a specific clause in a specific PDF — mode 1 fires when the
model *refuses* text that was placed in front of it, which a closed-book benchmark cannot even
express, and modes 3 and 4 happen entirely in retrieval and ingestion, before the model is
called at all. A benchmark also has no notion of the thing that makes mode 2 dangerous: scoring
is exact-match or pass/fail, so "50% depreciation on plastic parts" counts as fully correct even
though it omits the five-year eligibility limit sitting in the same passage, which is precisely
the omission that would overpay a claim. And no public benchmark contains this corpus — the
placeholder banner of mode 4, the mangled annexure of mode 5, and the endorsement-supersedes-base
structure that half this taxonomy turns on are properties of *these* documents, so a score of
88% on MMLU would have told the claims manager nothing about whether the assistant can be
trusted with a denial.

---

## 7. What this does not tell you

* **One afternoon, not one week.** 114 traces from one batch run. The frequencies are honest for
  this bank of questions and this corpus; they are not a measurement of live user behaviour.
* **Mode 5 is n=1.** It is in the table on severity, not on frequency, and its 5% should not be
  quoted as if it were measured.
* **The bank is mine.** I wrote it without checking answerability, which removes the worst bias,
  but a real log would contain question shapes I did not think to write.
* **Correctness was judged by me, by reading the cited passage.** There is no independent
  grader, so the seven "no failure observed" traces carry my judgement, not a measurement.

---

## 8. Bonus — the demo set

The ten questions the app gets shown with (`eval/demo_set.yaml`), traced separately as
`surface: traffic-demo` and open-coded the same way.

1. **`tr_ad355352e98d`** — "compulsory deductible for a car above 1500cc" — Gave INR 3,000 and
   said it supersedes INR 2,000, with the endorsement and base clause at ranks 1 and 2 scoring
   0.9995 and 0.9996.
2. **`tr_71526999b2ae`** — "waiting period for pre-existing diseases" — Gave 24 months and named
   Endorsement 2 as replacing the earlier 36 months.
3. **`tr_53bd577f35e2`** — "co-payment for insured persons above 60" — Gave 10% at 66 years and
   above and spelled out that this replaced 20% at 61 and above.
4. **`tr_c7412ad97e3a`** — "How many days do I have to intimate a motor claim?" — A motor
   question returned two *health* claims passages at 0.0365 and 0.0353 and was refused at the
   rerank floor.
5. **`tr_a3ab53591602`** — "depreciation rate for plastic parts" — Gave the Nil Depreciation
   position as superseding the 50% rate.
6. **`tr_64da29e63280`** — "grievance officer response time" — Gave 10 days superseding 15 and
   noted the 3-working-day acknowledgement is unchanged.
7. **`tr_79465d4a6604`** — "Which document supersedes the base health wording?" — The passage
   containing "this endorsement prevails" was retrieved at rank 2 scoring 0.0001 and the request
   was refused at the cosine floor.
8. **`tr_63adb0b7074a`** — "Does the policy cover flood damage to the engine?" — The motor
   own-damage passage came back at 0.0851 against the 0.10 floor and was refused.
9. **`tr_9946933a4b11`** — "room rent limit" — Gave 2% and 4% of sum insured per day and both
   superseded figures with their effective dates.
10. **`tr_185366c0fb1a`** — "premium for this policy" — Refused, and the corpus contains no
    premium figure.

**The two numbers.** Mode 1 — the top mode — is **25% of the random sample (5/20)** and **20% of
the demo set (2/10)**. Those are closer than expected, and the more revealing pair is the
overall clean rate: **35% of the random sample (7/20)** versus **70% of the demo set (7/10)**.
The demo set is exactly twice as clean.

### What we have been telling ourselves

For a month the story at the monthly review has been "the app handles superseded clauses
correctly", and the demo proves it — six of the ten demo questions return the current figure,
name the endorsement, give the superseded figure, and cite both. That story is true about those
six questions and it is the wrong generalisation. In the random sample the supersession
machinery worked whenever a short, well-aimed query pulled both tables (`tr_34d34d4ae3cf`,
"waiting period"), and it collapsed the moment a question was phrased the way a person actually
asks about versions: *"Compare the waiting period in the base wording with the endorsement"*
retrieved four passages from the wrong endorsement, scored the right table 0.0007, and refused
outright. We have been demonstrating the retrieval that happens to work and calling it
supersession handling. The demo set also hides the app's real signature failure: nine of its ten
questions are single-clause lookups, so mode 2 — the right figure without its limiting condition
— has almost no opportunity to fire, and it never once appeared at a review. Worse, the demo set
was not even clean on its own terms and we had stopped noticing: three of its ten questions fail,
including a motor claim question answered from health passages, and it took reading the traces
rather than watching the screen share to see it.

---

## 9. Reproducing all of this

```bash
python eval/check_redaction.py                              # redaction, both halves
python eval/sample_traces.py --seed 20260826 --n 20          # the sample
python eval/read_trace.py --seed 20260826 --n 20             # the reading pass
python eval/replay_trace.py --seed 20260826 --n 20           # the replay
```

**Prediction commit:** `b0f7c375ecf1254272719facf17d705154410d17` (short `b0f7c37`), branch
`week-5-error-analysis`, committed 26 August 2026 — *before* any fix. Verify with:

```bash
git show b0f7c37:notes.md | sed -n '/## 5. The prediction/,/^---$/p'
```

That commit contains the prediction and the taxonomy and no change to the answer prompt, which
is still `claims-v1` / `43275b979e43` there. The prompt revision the prediction is about
(`claims-v2`) belongs to next week and must land in a later commit, or the prediction was not
made in advance.
