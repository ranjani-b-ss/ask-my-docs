# Week 4 · Debugging retrieval — failure separation, hybrid search, before/after

Topic **D — Insurance claims**. One change, measured.

Every number below was produced by a command in this repo, not estimated.

---

## 1 · Separating the two kinds of wrong

"Wrong sometimes" can't be acted on, because the two kinds need opposite fixes. So the first
deliverable is a labeller, not a feature:

```bash
./.venv/bin/python eval/label_failures.py --corpus insurance --k 3 --no-llm
```

It runs each question **twice** — once with the abstain gates disabled to ask *"was the gold
passage even found?"*, and once as a user would experience it. Conflating those two is the
mistake the whole week is about.

| Label | Meaning | Where the fix lives |
|---|---|---|
| `RETRIEVAL_FAIL` | Gold passage never reached top-k. The model had no chance. | chunking, embeddings, hybrid, reranking |
| `GEN_FAIL_GATED` | Gold passage **was** in top-k; an abstain threshold refused it. | `config.py` thresholds |
| `GEN_FAIL_WRONG` | Gold passage was in top-k, model answered, answer missed the fact. | prompt or model |
| `FALSE_ANSWER` | Unanswerable question got answered. | abstain gates |

Splitting `GATED` from `WRONG` matters: both look identical from outside ("right document,
wrong answer") but one is a number in a config file and the other is a prompt.

### Baseline, insurance corpus, k=3

```
HIT-RATE@3 = 14/15 = 93%

retrieval-side failures : 1   (fix = chunking / hybrid / reranking)
generation-side failures: 1   (fix = thresholds / prompt / model)
false answers           : 2   (fix = abstain gates)
```

### The specific failure, with evidence — mentor check 1

`tyre-limit` — *"If my tyres are damaged in an accident, how much is payable?"*

```
tyre-limit    answerable    rank 1    cos 0.684    rr 0.025    GEN_FAIL_GATED
```

**Rank 1.** The correct clause ("50% of the cost of replacement") was the single
best-retrieved passage. Retrieval did its job perfectly. Then the cross-encoder scored it
**0.025**, below the 0.10 abstain threshold, and the app refused.

This is provably *not* a retrieval failure, and that matters commercially: a bigger embedding
model, a better chunker, or hybrid search would each cost effort and fix **nothing** here.
The fault is one threshold.

---

## 2 · The one change: BM25 hybrid with RRF fusion

**Why this one.** Dense embeddings match meaning, which is exactly why they miss things a
human finds obvious: a policy number, a UIN, a plan name, a clause reference. Those carry
almost no semantic content — to an embedding model `512N338V01` and `512N339V02` are nearly
identical. BM25 has the opposite bias: it rewards rare exact tokens and knows nothing about
meaning.

**Why RRF rather than a weighted score sum.** Cosine similarity (0–1) and BM25 (unbounded)
aren't comparable as numbers, but their *ranks* always are. RRF needs no score normalisation
and no per-corpus weight tuning — which is the point. A weighted sum would need re-tuning for
every document set, and fitting the tool to one corpus is the failure mode to avoid.

Implemented in [`src/keyword.py`](src/keyword.py) (~80 lines, standard library, no new
dependency) and fused in [`src/retriever.py`](src/retriever.py) — `reciprocal_rank_fusion()`.

**It is exactly one change.** Reranking already existed from Week 3. Nothing else was touched
in the same measurement.

---

## 3 · Before and after — mentor check 3

Reranker **off** for both runs, so the hybrid change is isolated. Gates off, because this
measures retrieval, not abstention.

| Corpus | Questions | dense-only | hybrid | Δ |
|---|---:|---:|---:|---:|
| `insurance` (7 docs) | 15 | 13/15 = **87%** | 14/15 = **93%** | **+6pp** |
| LIC policy PDF (1 doc) | 10 | 9/10 = **90%** | 9/10 = **90%** | **0** |

Two questions moved on the insurance corpus:

| Question | dense | hybrid |
|---|---|---|
| `claim-decision-clock` | **MISS** | rank 2 |
| `health-reimbursement-window` | rank 3 | rank 2 |

`claim-decision-clock` is the interesting one — it went from *not retrieved at all* to rank 2.
The query mentions a decision window; the amending endorsement is `END-2026-03`, and the
overlapping exact tokens are what BM25 rewards and the embedding averaged away.

Reproduce:

```bash
./.venv/bin/python eval/label_failures.py --corpus insurance --k 3 --no-llm
```

---

## 4 · What the change did NOT fix — mentor check 4

This is the part worth being explicit about.

**a) Zero improvement on the single-document corpus.** LIC stayed at 90%. Obvious in
hindsight and worth stating: with one document there is no *wrong document* to fetch, so the
failure mode hybrid addresses doesn't exist there. **Hybrid search buys nothing on a
single-document corpus.**

**b) Two questions still fail, and neither is a keyword problem:**

| Question | Corpus | Why hybrid can't help |
|---|---|---|
| `motor-intimation-window` (needle `72 hours`) | insurance | BM25 added 7 candidates, best score 6.79 — the gold chunk was still not in the top 3. The competing base-wording clause is lexically *and* semantically closer. Both retrievers agree, and both are wrong. |
| `surrender-when` (needle `any time`) | LIC | The needle is a common phrase — BM25 gives `any time` almost no IDF weight, so keyword search has no purchase. |

**c) It fixes none of the three non-retrieval failures.** `tyre-limit` (gated),
`dental-waiting-period` and `ncb-after-two-claims` (false answers) are all unaffected by
definition — they were never retrieval problems. Correctly diagnosing them is why they
weren't touched.

**d) Two hypotheses I tested and abandoned**, recorded because the wrong guesses are part of
the method:

1. *"Dense retrieval will miss exact document codes."* Measured **4/4** on real codes. The
   codes appear as literal text in the documents and the contextual headers reinforce them.
   Wrong.
2. *"Harder question types will expose failures."* Measured 50% hit-rate — then verification
   showed **all five "failures" were correct absences**. `Exclusion`, `not payable` and
   `lakh` occur **0 times** in a sample policy document, whose schedules are blank. My gold
   labels were wrong, not the app. Wrong again.

Both were caught by grepping the extracted text before trusting the metric. A gold label
that asserts a fact the document doesn't contain silently inverts the measurement.

---

## 5 · Honest limits

- **Baseline was already high** (87–93%), so headroom was small. A +6pp gain on 15 questions
  is **one question** — real, reproducible, and not a large sample. It should be re-measured
  on a bigger question set before being called a robust improvement.
- **Hybrid is skipped when a metadata filter is active.** BM25 here scans the whole
  collection, so fusing its results would smuggle back chunks the filter deliberately
  excluded. Correct behaviour, but it means `--doc-type` and hybrid don't currently compose.
- **Question sets are small** — 15 and 10 answerable questions. Enough to detect a real
  regression, not enough for a confident effect size.
- **Not tried, deliberately** (the brief asks for one change): query rewriting, HyDE, MMR,
  a hosted reranker.
