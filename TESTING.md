# Test protocol

Every command below has been run and the expected output is the **actual** output, not a
prediction. Run them in order. Total time ~10 minutes.

Working directory for everything: `~/Desktop/ask-my-docs`

```bash
cd ~/Desktop/ask-my-docs
```

---

## Step 0 · Confirm the environment

```bash
./.venv/bin/python cli.py status
```

**Expect:**

```
Corpora available: insurance, uploaded

Indexes built:
  insurance_bgesmallenv15_recursive_800_150     59 chunks
  ...

Answer models:
    ollama     not configured  llama3.2:3b
    openai     not configured  gpt-4o-mini
    anthropic  not configured  claude-opus-5
  * gemini     ready           gemini-flash-latest

  (* = active, from LLM_PROVIDER in .env)
```

The `*` marks the active provider. **Gemini is configured, so you get written prose
answers** — expect `mode=gemini` on every answer below.

If no provider is ready, the app falls back to **retrieval-only mode** and quotes the
winning passage instead. Retrieval, citations and all four refusal paths still work, so
every mentor check still passes — you just get a quote instead of a sentence.

*Note on the Gemini model:* the default is the alias `gemini-flash-latest`, not a pinned
version. Google gates older concrete versions (`gemini-2.5-flash` among them) to
pre-existing users, so a pinned id that works on one key 404s on a newer one. If you ever
see a 404 naming a model, set `GEMINI_MODEL` in `.env` to something your key can reach.

If the index is missing, build it:

```bash
./.venv/bin/python cli.py ingest
```

**Expect:** `Ingested 7 documents -> 59 chunks`, then a list of the 7 files, then
`vectors: 59 x 384`.

---

## Mentor check 1 · Can it answer correctly from the documents?

```bash
./.venv/bin/python cli.py ask "What is the compulsory deductible for a car above 1500cc?"
```

**Expect** (with Gemini configured) an answer like:

```
The compulsory deductible for a car with a cubic capacity above 1500cc is
INR 3,000 [1]. This superseded the earlier base policy wording, which specified
a compulsory deductible of INR 2,000 [1][2].

mode=gemini  grounded=True
diagnostics: {... 'cited': [1, 2], 'invented_citations': [] ...}
```

Point at `invented_citations: []` — that is the third gate confirming every marker the
model wrote maps to a passage that was really supplied.

The important part: the *base policy* says INR 2,000. The endorsement raised it to 3,000.
The app returned the **current** figure, not the superseded one. A keyword search over
these documents returns 2,000 and is confidently wrong.

Second one, to show it isn't a fluke:

```bash
./.venv/bin/python cli.py ask "At what percentage of IDV is a vehicle a constructive total loss?"
```

**Expect** **70%** (endorsement END-2026-01), not the 75% in the base wording.

---

## Mentor check 2 · Does every answer show its source?

Same command as above — look at the `Sources` block:

```
Sources
  [1] Endorsement 1 to the Private Car Package Policy > 2. Amendment to Clause 2.2 — Compulsory deductible
      END-2026-01 · effective 2026-04-01 · score 0.996
      /Users/softsuave/Desktop/ask-my-docs/corpora/insurance/endorsements/END-2026-01-motor.md
```

Four things to point at: the **document title**, the **clause** inside it, the
**effective date** (this is what resolves the supersession), and the **file path** on disk.

To prove citations are enforced rather than cosmetic, mention the third gate: if the model
writes an answer citing `[7]` when only 5 passages were supplied, the answer is
**discarded** and the passages shown instead. Verified in
[`src/generator.py`](src/generator.py) — `_cited_indices()` and the `unverified` mode.

To show a PDF citation with a page number:

```bash
./.venv/bin/python cli.py ask "What is the grace period for paying premium?"
```

**Expect** a citation ending in `p.1` — that's the generated PDF, proving the PDF loader
tracks page numbers.

---

## Mentor check 3 · Does it admit when it doesn't know?

**This is the strongest part of the demo. Run both — they fail on different gates.**

### 3a · Nothing in the corpus is close (cosine gate)

```bash
./.venv/bin/python cli.py ask "What is the cyber liability cover limit?"
```

**Expect:**

```
I don't know — that isn't covered in the documents I have.

_Why: Best vector similarity 0.62 is below the 0.62 threshold — nothing in the
documents is close enough to this question._

mode=abstained  grounded=False
diagnostics: {... 'best_cosine': 0.6158, 'best_rerank': 0.0 ...}
```

### 3b · On-topic but doesn't answer (reranker gate)

```bash
./.venv/bin/python cli.py ask "How much is payable for road ambulance charges?"
```

**Expect:**

```
I don't know — that isn't covered in the documents I have.

_Why: Passages were retrieved, but the cross-encoder scored the best one 0.00,
below the 0.35 threshold — they are topically near the question but do not
answer it._

diagnostics: {... 'best_cosine': 0.6509, 'best_rerank': 0.0 ...}
```

**Say this out loud, it's the whole point:** the ambulance question **passed** the cosine
gate at 0.6509 — it *is* about medical claims, so it looks relevant to the embedding model.
Only the cross-encoder caught that no passage actually answers it, scoring the best one at
**0.000**. A single-threshold design misses this entire class of question.

And the calibration matters: unrelated text scores **0.52–0.62** cosine on this embedding
model, never near zero. The obvious threshold of 0.5 would **never refuse anything**. That
number came from measuring, not guessing.

Two more if the mentor pushes:

```bash
./.venv/bin/python cli.py ask "How do I change the nominee recorded on my policy?"
```

```bash
./.venv/bin/python cli.py ask "What is the waiting period before dental treatment becomes payable?"
```

Both abstain. The second is the cruel one — dental *is* mentioned (as an exclusion) and
waiting periods *do* exist, but there's no dental waiting period.

---

## Mentor check 4 · Did you try more than one chunk size?

### 4a · The measured sweep

```bash
./.venv/bin/python eval/run_eval.py
```

Takes ~2 minutes. Builds five indexes and scores 22 gold questions against each.

**Expect exactly:**

```
| chunking                           | chunks | hit@k | MRR  | current | abstain |
| fixed, 300 chars, 0 overlap        |    114 |   87% | 0.71 |     62% |     71% |
| recursive, 300 chars, 60 overlap   |    169 |   93% | 0.89 |     88% |     86% |
| recursive, 800 chars, 150 overlap  |     59 |  100% | 0.92 |     88% |     71% |
| recursive, 1600 chars, 200 overlap |     28 |   93% | 0.69 |     50% |     71% |
| heading, 2000 chars, 0 overlap     |     73 |   87% | 0.81 |     88% |     86% |

best by MRR: recursive, 800 chars, 150 overlap
```

What to say about it:

- **800 is the sweet spot** — roughly one clause per chunk. Perfect recall, best ranking.
- **1600 is the surprise** — MRR *collapses* to 0.69, the **worst of the five**, while
  recall stays at 93%. The answer is in the chunk but buried among unrelated clauses, so
  the chunk's embedding averages several topics and matches nothing sharply. Bigger chunks
  cost you precision.
- **`fixed` is worst overall** at the same size because it ignores document structure.
- **Abstain rate rises at small sizes** (71% → 86%) — smaller chunks are more focused, so
  an irrelevant chunk scores lower and trips the gate more readily. Chunk size changes the
  *refusal* behaviour too, not just retrieval.

### 4b · The demo that lands — chunk size changing the actual answer

Same question, two chunk sizes. **Run both back to back:**

```bash
./.venv/bin/python cli.py --chunk-size 800 --overlap 150 ask "What is the waiting period for pre-existing diseases?"
```

**Expect** `| Pre-existing diseases | 24 months |`, cited to **END-2026-02**, effective
2026-05-01, score 0.994.

```bash
./.venv/bin/python cli.py --chunk-size 1600 --overlap 200 ask "What is the waiting period for pre-existing diseases?"
```

**Expect** `| Pre-existing diseases | 36 months |`, cited to **PW-HEALTH-002**, effective
2025-04-01, score 0.562.

**24 months versus 36 months.** Identical question, identical documents, identical model —
only the chunk size differs, and one of them is wrong. The 1600-char chunk swept the
endorsement's amendment table in with several unrelated clauses, so its embedding stopped
matching the query sharply and the superseded base wording won instead. Note the score
collapse too: 0.994 → 0.562.

Nothing communicates "chunk size matters" better than a wrong number.

### 4c · Turn the reranker off

```bash
./.venv/bin/python cli.py ask "What mileage rate applies to an electric car?" --no-rerank --show-chunks
```

Compare against the same command without `--no-rerank`. Shows the bi-encoder's raw ordering
versus the cross-encoder's, which is the **bi-encoder vs cross-encoder** topic made visible.

---

## Step 5 · The web app

```bash
./.venv/bin/python -m streamlit run app.py
```

Opens `http://localhost:8501`.

Demo path:

1. **Sidebar → Chunking** — drag chunk size from 800 to 1600, re-ask the pre-existing
   disease question, watch the answer change. Same demo as 4b but live.
2. **Sidebar → Retrieval** — toggle *Cross-encoder reranking* off and on.
3. **Sidebar → Abstain thresholds** — drop min cosine to 0.30 and re-ask the cyber
   liability question. It now **answers** with junk. That shows the threshold is doing real
   work.
4. **Sidebar → Answer model** — show all four providers (ollama / openai / anthropic /
   gemini) and that unconfigured ones fall back gracefully.
5. **Expand "Retrieved passages and diagnostics"** on any answer — shows all 5 passages
   with cosine and rerank scores side by side.

---

## Step 6 · Upload your own document

This is the part to demo if asked "can it work on *my* file?"

1. In the UI, drag a PDF into the uploader.
2. Click **Ingest documents**. Expect a metrics row: documents, chunks, median chunk size,
   vector dim 384.
3. Ask something answerable from that PDF.
4. **Then ask something answerable from the insurance corpus but absent from your PDF** —
   e.g. *"What No Claim Bonus applies after three claim-free years?"*

**Expect: it abstains.** The uploaded documents get their own index, so a question about
your PDF can never be silently answered from sample data. Verified — this is the corpus
isolation guarantee.

From the CLI instead:

```bash
./.venv/bin/python cli.py ingest --corpus uploaded
```

```bash
./.venv/bin/python cli.py ask "your question here" --corpus uploaded
```

---

## Step 7 · Metadata filtering (bonus)

Search only the endorsements, ignoring base policy wordings:

```bash
./.venv/bin/python cli.py ask "What is the deductible?" --doc-type endorsement
```

Or only documents effective this year:

```bash
./.venv/bin/python cli.py ask "What is the deductible?" --effective-after 2026-01-01
```

The filter runs **before** the vector comparison, so it removes whole classes of wrong
answer for free — often more effective than a better embedding model.

---

## Known rough edges — worth naming before the mentor finds them

Being upfront about these reads better than being caught by them.

1. **A citation can name the wrong clause in a merged chunk.** Ask
   *"How many days do I have to submit documents for a health reimbursement claim?"* — the
   answer (30 days) is correct and present in the retrieved passage, but the citation label
   says *"4. Amendment to Clause 9 — Co-payment"* because the 800-char chunk merged two
   short sections and the label takes the first one. The fix is to label chunks with the
   section the *matched text* sits in, not the section the chunk starts in.
2. **Retrieval is dense-only.** No BM25 hybrid, so an exact string like a policy number can
   be missed where keyword matching would nail it.
3. **Abstain rate is 71%, not 100%.** Two of the seven near-miss questions get through.
   Raising thresholds catches them but starts refusing real questions — it's a genuine
   precision/recall trade, not an oversight.
4. **Thresholds are tuned to this corpus** and need re-checking with `eval/run_eval.py` on
   a different document set.
5. **The corpus is a labelled placeholder.** The assigned PDF isn't ingested yet; when it
   is, `eval/questions.yaml` needs rewriting against it or the numbers are meaningless.
