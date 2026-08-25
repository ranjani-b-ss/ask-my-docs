# Ask My Documents — an Insurance Claims RAG system

Week 3 · Module 2 · Topic **D — Insurance claims**

Ask a question, get an answer built **only** from the indexed documents, with a citation on
every claim. When the documents don't cover the question, the app says *"I don't know"*
instead of inventing a policy term.

```
┌─ Ingest (once) ──────────────────────────────────────────────┐
│  Load  ──▶  Chunk  ──▶  Embed  ──▶  Store                    │
│  md/html/pdf  section-aware  bge-small  chroma (HNSW)        │
└──────────────────────────────────┬───────────────────────────┘
                                   │ the index
┌─ Ask (per question) ─────────────▼───────────────────────────┐
│  Question ─▶ Embed query ─▶ Vector search (top 20)           │
│      ─▶ [gate: cosine floor] ─▶ Cross-encoder rerank (→5)    │
│      ─▶ [gate: rerank floor] ─▶ Generate ─▶ [gate: cites?]   │
│      ─▶ Answer + sources                                     │
│  Any gate failing ─▶ "I don't know", with the reason         │
└──────────────────────────────────────────────────────────────┘
```

---

# Part 1 · User guide

## Setup

Requires Python 3.10–3.13. **Not 3.14** — `fastembed` has no wheels for it yet.

```bash
cd ~/Desktop/ask-my-docs
```

```bash
python3.13 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt
```

First run downloads two ONNX models (~220 MB total) and caches them. After that the whole
pipeline works **offline**.

## Run it — two ways

### The web app (recommended)

```bash
./.venv/bin/python -m streamlit run app.py
```

Opens on `http://localhost:8501`. Upload your PDF, click **Ingest documents**, ask a
question. The sidebar exposes every knob live: chunk size, overlap, top-k, reranker on/off,
both abstain thresholds, and which model writes the answer.

### The command line

```bash
./.venv/bin/python cli.py ingest
```

```bash
./.venv/bin/python cli.py ask "What is the compulsory deductible for a car above 1500cc?"
```

```bash
./.venv/bin/python cli.py status
```

Useful flags on `ask`:

| Flag | What it does |
|---|---|
| `--show-chunks` | Print every retrieved passage with its scores — the fastest way to debug a bad answer |
| `--no-rerank` | Skip the cross-encoder, so you can see the raw bi-encoder ordering |
| `--doc-type endorsement` | Metadata filter: search only endorsements |
| `--effective-after 2026-01-01` | Metadata filter: only documents effective on/after a date |
| `--chunk-size 300 --overlap 60` | Query a different chunking index |
| `--no-llm` | Force retrieval-only mode |

## Using your own documents

Two options.

**Through the UI** — drag files into the uploader and click Ingest. They're written to
`corpora/uploaded/` and indexed into their own collection, kept completely separate from
the sample pack. This matters: a question about your PDF can never be answered from sample
data.

**On disk** — drop files into `corpora/<name>/`, then:

```bash
./.venv/bin/python cli.py ingest --corpus <name>
```

Supported: `.pdf`, `.md`, `.html`, `.htm`, `.txt`.

**Add metadata for your PDF.** PDFs carry no useful metadata of their own, so create
`corpora/<name>/metadata.yaml`:

```yaml
your-policy.pdf:
  document_id: PW-MOTOR-001
  title: Private Car Package Policy
  doc_type: policy_wording
  effective_date: 2025-04-01
```

`effective_date` is what lets the system prefer a later endorsement over a superseded base
clause, and `document_id` is what appears in the citation. Without them the app still
works, but recency filtering and clean citations don't.

## Choosing the answer model

Set `LLM_PROVIDER` in `.env` (copy `.env.example` first), or switch it live in the sidebar.

| Provider | Cost | Setup |
|---|---|---|
| `ollama` | Free, offline | `brew install ollama`, `ollama serve`, `ollama pull llama3.1:8b` |
| `gemini` | Generous free tier | `GEMINI_API_KEY` in `.env` |
| `openai` | Paid | `OPENAI_API_KEY` in `.env` |
| `anthropic` | Paid | `ANTHROPIC_API_KEY` in `.env` |

**Nothing is required.** With no provider configured the app runs in **retrieval-only
mode** — it quotes the winning passage verbatim instead of writing prose. Retrieval,
citations, and all four refusal paths still work, so the app is fully demonstrable with no
key and no install.

You add keys to `.env` yourself. The app reads them from the environment, never writes them
to disk, and never logs them. `.env` is gitignored.

## Running the chunking evaluation

```bash
./.venv/bin/python eval/run_eval.py
```

Builds five indexes at different chunk sizes and scores all 22 gold questions against each.
Add `--detail` for per-question pass/fail, or `--no-rerank` to isolate the reranker's
contribution.

To tune the abstain thresholds against your own labelled questions:

```bash
./.venv/bin/python eval/calibrate.py --corpus uploaded --questions eval/questions_lic.yaml --detail
```

Use it whenever you swap in a document set that behaves differently — real PDFs score lower
across the board than clean Markdown.

## Reading the traces

Every request appends one replayable JSON object to `traces/traces.jsonl`, with the retrieved
chunk ids and scores, the prompt version and hash, the model and its parameters, and the raw
output. Claimant identifiers are stripped by `src/redact.py` **before** the line is written.

```bash
./.venv/bin/python eval/check_redaction.py                     # prove that ordering holds
./.venv/bin/python eval/sample_traces.py --seed 20260826 --n 20 # seeded random sample
./.venv/bin/python eval/read_trace.py --seed 20260826 --n 20    # read them with passage text
./.venv/bin/python eval/replay_trace.py --seed 20260826 --n 20  # replay one from the trace alone
```

The error analysis built from those traces is in [`taxonomy.md`](taxonomy.md) — five ranked
failure modes with counts, frequencies and severities — with the full working, the twenty
open-coding sentences and the replay evidence in [`notes.md`](notes.md).

To generate traffic against a corpus so there is something to read:

```bash
./.venv/bin/python scripts/generate_traffic.py --sleep 2
```

---

# Part 2 · How it works

Six stages, one file each, so every concept on the syllabus maps to a place in the code.

| Stage | File | Syllabus topic |
|---|---|---|
| 1. Load | [`src/loader.py`](src/loader.py) | Loading PDFs and web pages |
| 2. Chunk | [`src/chunker.py`](src/chunker.py) | Chunking strategies, size & overlap |
| 3. Embed | [`src/embedder.py`](src/embedder.py) | Embeddings, BGE, bi- vs cross-encoder |
| 4. Store | [`src/store.py`](src/store.py) | Vector DBs, HNSW, Chroma |
| 5. Retrieve | [`src/retriever.py`](src/retriever.py) | Similarity search, top-K, metadata filtering |
| 6. Generate | [`src/generator.py`](src/generator.py) | Grounded generation & citations |

Plus [`src/llm.py`](src/llm.py) (the four-provider adapter) and
[`src/pipeline.py`](src/pipeline.py) (ties the stages together).

## Stage 1 · Loading

Three file formats become one uniform `LoadedDoc`, so everything downstream is
format-blind. Two details are load-bearing:

**HTML needs its chrome stripped.** Nav bars and footers become chunk text otherwise, and
they match *every* query weakly, polluting retrieval. `loader.py` drops
`<script>/<style>/<nav>/<footer>/<header>/<aside>` before extracting.

**Tables must survive as tables.** A table cell divorced from its column header is
useless — "INR 3,000" means nothing without "compulsory deductible, above 1500cc". Tables
are converted to pipe-delimited rows and kept whole.

**PDFs track page numbers** so a citation can say `p.2`.

## Stage 2 · Chunking

Three genuinely different strategies, not one with a size parameter:

- **`fixed`** — cut every N characters, ignoring structure. The naive baseline, kept
  deliberately so the eval has something to beat.
- **`recursive`** — split on the biggest natural boundary that fits (blank line → line →
  sentence → word), respecting headings. What most production systems do, and the default.
- **`heading`** — one chunk per clause. Great for policy documents, but chunk sizes become
  uneven.

Two things matter more than chunk size:

**Overlap** repeats the tail of one chunk at the head of the next, so a fact straddling a
boundary survives intact somewhere.

**Contextual headers.** Each chunk is embedded with its document title and heading trail
prepended: `[Own Damage Section > 2.2 Compulsory deductible]`. A bare chunk reading
"INR 3,000" is nearly unretrievable; the same chunk labelled with its clause is easy to
find. `Chunk.text` keeps the original for display, `Chunk.embed_text` carries the header.

## Stage 3 · Embeddings

An embedding turns text into 384 numbers positioned so that similar *meaning* lands
nearby. That's what lets "how long do I have to file a claim?" match a passage saying
"submission window is 21 days" — no shared keywords at all.

Two model types, which is the **bi-encoder vs cross-encoder** topic:

**Bi-encoder** (`bge-small-en-v1.5`) encodes query and chunk *separately*. Chunk vectors
are computed once at ingest and reused forever, so it scales — but the query never "sees"
the chunk, so scoring is approximate.

**Cross-encoder** (`ms-marco-MiniLM-L-6-v2`) feeds query and chunk through the model
*together* and outputs one relevance score. Far more accurate, far too slow for the whole
corpus.

So: retrieve 20 candidates with the bi-encoder, rescore just those 20 with the
cross-encoder, keep 5. Best of both.

**Asymmetric search:** BGE was trained with an instruction prefix on queries only, so
`embed_query()` prepends it and `embed_passages()` doesn't. Skipping it still works, just
measurably worse.

## Stage 4 · Storage

Chroma holds the vectors in an **HNSW** index. Comparing a query against every vector is
exact but linear; HNSW builds a navigable graph so a search visits a few hundred nodes
instead of the whole collection. It's *approximate* — in exchange for being orders of
magnitude faster it may occasionally miss a true nearest neighbour. Every production vector
database makes that trade.

Collections are named `{corpus}_{embed_model}_{chunk_config}`. All three parts matter:

- **corpus** — keeps uploaded documents from being searched alongside the sample pack.
- **embedding model** — vectors from different models have different dimensions and aren't
  comparable. Switching `EMBED_PROVIDER` builds a fresh index rather than corrupting the
  existing one.
- **chunk config** — lets the eval hold five chunk sizes side by side instead of
  re-ingesting between measurements.

Distance is set to cosine explicitly. Chroma defaults to squared L2, which is much harder
to reason about when picking a similarity threshold.

## Stage 5 · Retrieval and the abstain gates

**Metadata filtering** runs *before* the vector comparison — `doc_type == "endorsement"`,
or `effective_date >= "2026-01-01"`. Cheap, and often more effective than a better
embedding model, because it removes whole classes of wrong answer.

**The recency tie-break.** An amending clause and the clause it amends are near-duplicates
in meaning, so the cross-encoder scores them almost identically (1.000 vs 0.999 is typical)
and their order is effectively arbitrary. When the stale one wins, a grounded,
correctly-cited answer is still *wrong*. So scores are rounded into coarse buckets and
recency decides within a bucket — genuine relevance still dominates, but near-ties break
toward the later `effective_date`.

This was measured, not assumed. Supersession precedence went **50% → 88%** and MRR
**0.80 → 0.92**. It mattered more than any chunk-size change.

## Stage 6 · Grounded generation

Three things keep the model honest:

1. **Numbered context only.** The prompt contains the retrieved passages and nothing else,
   and says prior knowledge is off-limits.
2. **Mandatory citations.** Every factual sentence must carry a `[n]` marker. A claim with
   no marker has nowhere to hide.
3. **Post-generation verification.** We check the markers actually exist. A model citing
   `[7]` when five passages were supplied is drifting, so the answer is withheld rather
   than shown.

## Why the app refuses — four separate paths

This is the part worth explaining on Friday, because it's where most implementations are
weak. "Say I don't know" left to the prompt alone fails under pressure: a model shown a
weakly-related chunk will paraphrase it rather than decline.

| Gate | Fires when | Catches |
|---|---|---|
| Cosine < 0.62 | Nothing in the corpus is close | *"Can I bring my dog to the office?"* |
| Rerank < 0.35 | Passages are on-topic but don't answer | *"What is the waiting period for dental treatment?"* |
| Model returns `NOT_IN_DOCUMENTS` | The model itself declines | Subtle gaps the scores missed |
| No valid `[n]` citations | The answer isn't traceable | A drifting model |

The first two fire **before the LLM is called at all**, which makes the refusal
deterministic, explainable, and free.

**The thresholds were measured, not guessed** — and they are one global pair, not a
per-corpus table. `eval/calibrate.py` sweeps candidate thresholds over labelled questions
from two deliberately different corpora (clean synthetic Markdown, and a real 21-page LIC
policy PDF) and reports which pair separates answerable from unanswerable best. The current
values score 36/39 across both.

Two findings from that sweep are worth knowing:

- **The cosine gate does little work.** Anything from 0.55 to 0.62 gives identical results;
  only 0.64 improves them. The cross-encoder is what actually separates answerable from not.
- **Unrelated text never scores near zero on cosine** — it sits at 0.51–0.68 depending on
  the corpus. The obvious threshold of 0.5 would never refuse anything.

To re-measure on your own documents:

```bash
./.venv/bin/python eval/calibrate.py --corpus uploaded --questions eval/questions_lic.yaml --detail
```

It prints both score distributions, whether they separate cleanly, and the best cut. If
they overlap it says so and names the overlap band, because that band is the part no
threshold can fix.

The two gates also catch different things. Cosine catches *nothing relevant exists*. The
reranker catches something subtler — passages about the right topic that don't answer the
question. Those clear the cosine bar. A single-threshold design misses that class entirely.

## Provider choice doesn't affect retrieval

`llm.py` is the only file that knows which vendor is in use. Worth understanding: **if the
app returns a wrong figure, switching provider will not fix it**, because the error happened
before generation. Only the answer's wording changes.

Each provider has a genuinely different call shape, and getting it wrong is a hard failure:

- **Ollama / OpenAI** — system prompt as a `role: "system"` message, `temperature: 0`.
- **Anthropic** — system prompt is a top-level `system=` argument, and **`temperature` is
  rejected outright** (removed on Opus 5). `max_tokens` also bounds thinking *and* the
  answer together, so sizing it for the answer alone truncates mid-sentence.
- **Gemini** — system prompt is its own `system_instruction` object, user text wraps in a
  `parts` list, sampling lives under `generationConfig`, and the key goes in a header (a key
  in a URL ends up in logs).

---

# Part 3 · What the evaluation shows

`eval/questions.yaml` holds 22 gold questions in three kinds:

- **answerable** (7) — the fact sits in one place. Tests plain retrieval.
- **superseded** (8) — an endorsement overrides the base wording. The system must surface
  the *current* figure and outrank the stale one. A keyword search gets these confidently
  wrong.
- **unanswerable** (7) — the fact is absent. Must abstain. Three are marked `near_miss`:
  topically adjacent, so only the cross-encoder catches them.

Retrieval is measured, not the wording — chunk size changes *what the model is shown*, and
if the right passage never reaches the prompt, no prompting recovers it. No LLM is called,
so the numbers are deterministic.

| Chunking | Chunks | hit@k | MRR | current | abstain |
|---|---:|---:|---:|---:|---:|
| fixed, 300, 0 overlap | 114 | 87% | 0.71 | 62% | 71% |
| recursive, 300, 60 | 169 | 93% | 0.89 | 88% | 86% |
| **recursive, 800, 150** | **59** | **100%** | **0.92** | **88%** | **71%** |
| recursive, 1600, 200 | 28 | 93% | 0.69 | 50% | 71% |
| heading, 2000, 0 | 73 | 87% | 0.81 | 88% | 86% |

**What changes with chunk size:**

- **Too small (300 chars)** — 169 chunks, and clauses get split. Recall holds up because
  overlap rescues most facts, but ranking suffers: a fragment matches the query without
  containing the whole answer.
- **The sweet spot (800)** — one clause per chunk, roughly. Best MRR and perfect hit@k.
- **Too large (1600)** — MRR collapses to 0.69, the worst of the five, and supersession
  drops to 50%. The answer *is* in the chunk, but buried among unrelated clauses, so the
  chunk's embedding is an average of several topics and matches nothing sharply. This is
  the most counter-intuitive result: bigger chunks hurt precision even while keeping recall.
- **`fixed` is worst overall** at the same size, because it ignores structure entirely.

Note that abstain rate goes *up* at the small sizes. Smaller chunks are more focused, so an
irrelevant chunk scores lower and trips the gate more readily — chunk size affects the
refusal behaviour too, not just retrieval.

## A real bug the eval caught

Before the splitter was section-aware, *"What is the per diem for travel to Mumbai?"*
returned the **accommodation** table. The per-diem table had been orphaned from its
`## 5. Meals and per diem` heading, so the chunk carrying the numbers was labelled with the
*previous* section and scored **0.000** on the reranker, ranking 5th. A different section
won.

Fixing the splitter to treat headings as hard boundaries moved it to rank 1. That single
bug is the clearest demonstration of why chunking matters — nothing about the embedding
model, the vector store, or the prompt was wrong.

---

# Part 4 · The sample corpus

`corpora/insurance/` holds a **placeholder** pack — 7 documents about a fictional insurer,
"Meridian Assurance Limited". Every file is headed as synthetic training data. Replace the
directory with your assigned pack; nothing in the pipeline is topic-aware.

The structure is deliberate: a base policy wording **plus an endorsement pack that
supersedes it**.

| Question | Base wording says | Endorsement says |
|---|---|---|
| Deductible above 1500cc | INR 2,000 | **INR 3,000** |
| Pre-existing disease wait | 36 months | **24 months** |
| Constructive total loss | 75% of IDV | **70% of IDV** |
| Claim decision window | 30 days | **15 days** |

That one choice gives you a demo where a keyword match returns the *wrong* number, which is
what forces real citations and makes `effective_date` filtering meaningful rather than
decorative. Three formats (5 Markdown, 1 HTML "web page", 1 generated PDF) exercise all
three loaders.

---

# Project layout

```
ask-my-docs/
├── app.py                     Streamlit UI (upload → ingest → ask)
├── cli.py                     ingest / ask / status
├── src/
│   ├── config.py              every tunable knob
│   ├── loader.py              stage 1 — md, html, pdf → LoadedDoc
│   ├── chunker.py             stage 2 — three strategies, size, overlap
│   ├── embedder.py            stage 3 — bi-encoder + cross-encoder
│   ├── store.py               stage 4 — Chroma / HNSW
│   ├── retriever.py           stage 5 — top-k, filters, abstain gates
│   ├── generator.py           stage 6 — grounded prompt, citation checks
│   ├── llm.py                 provider adapter (ollama/openai/anthropic/gemini)
│   └── pipeline.py            ingest() and ask()
├── eval/
│   ├── questions.yaml         22 gold questions
│   └── run_eval.py            chunk-size sweep
├── corpora/insurance/         placeholder corpus — replace with the assigned pack
└── scripts/make_sample_pdf.py generates the one PDF in the placeholder corpus
```

# Known limitations

- **Retrieval is dense-only.** No BM25/keyword hybrid, so an exact term like a policy
  number can be missed where lexical matching would nail it. Hybrid retrieval is the
  obvious next step.
- **No threshold separates a qualifier mismatch.** A question genuinely *about* the right
  topic that asks for a qualifier the documents don't cover scores high, because the
  retrieved passage really is on topic. "What No Claim Bonus applies to a rental car hired abroad?" scores 0.67 on the
  reranker because the retrieved passage really is about No Claim Bonus. No score threshold
  catches that — the model's own `NOT_IN_DOCUMENTS` gate does, which is why there are three
  gates and not two.
- **The cross-encoder occasionally scores a real answer very low.** One of 15 gold
  questions ("if my tyres are damaged, how much is payable?") scores 0.026 despite the
  correct clause being retrieved at high cosine, so the rerank gate refuses it. Lowering
  the threshold far enough to catch it would gut abstention. This is a reranker limitation,
  not a tuning one.
- **The abstain thresholds are a precision/recall trade.** At 800 chars the abstain rate is
  71%, not 100% — two near-miss questions get through the gates. Raising the thresholds
  catches them but starts refusing real questions.
- **No conversation memory.** Each question is independent; follow-ups like "what about
  for a two-wheeler?" don't resolve.
- **Chunk size is fixed per index.** No adaptive sizing per document type.
