# Claims Triage & Coverage Assistant

Week 12 capstone · Variant D. One command takes a claim number and returns a **referral packet
for a human adjuster**: whether the policy was in force on the loss date, the policy wording
that was in force *on that date* (with document, version and effective date), and three
separate numbers — deductible (or co-payment), sub-limit, policy limit.

**What it never does.** It never states whether a claim is covered, payable, excluded or
declined. `decision` is always `null`, enforced in code (see [ARCHITECTURE.md](ARCHITECTURE.md)),
and every run ends in a referral to an adjuster — including one where the model provider is down (SEAMS.md S15, fixed and tested with a stub provider).

> **Draft status.** The system, its offline tests and the 36-case integrated eval are done
> (results in [EVAL_REPORT.md](EVAL_REPORT.md), itself still a draft: the final non-coverage list is pending).
> All data is **synthetic** — the claims, policies, people and addresses were written for this
> exercise.

---

## 1. Run it (about 10 minutes, mostly a one-off model download)

Needs Python 3.10–3.13 (**not** 3.14) and a Gemini API key.

```bash
cd ask-my-docs
```

```bash
python3.13 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Edit `.env`: set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=<your key>`. `.env` is gitignored.
Triage needs a model — unlike the Week 3 `ask` command there is no key-free mode.

Build the search index the capstone reads (downloads two ONNX models, ~220 MB, once; the index is not committed). It uses the `structured`
chunking strategy, which keeps a bullet list and its wrapped lines whole (WEEK11.md §9):

```bash
./.venv/bin/python cli.py --strategy structured ingest
```

The default `ingest` (no flag) builds the older `recursive` index. The capstone does not read it; it is kept only so the stored Week 12 traces
(whose chunk ids and context hashes were recorded against it) can still be rebuilt and verified by `eval/cap_judge.py`.

Triage a claim — **this is the single entry point**:

```bash
./.venv/bin/python cli.py triage CLM-2026-00601 --model gemini-3.5-flash-lite
```

Expect ~30 s the first time (the two MCP servers start and load their models before the clock
starts) and 10–60 s per claim after that.

**Why `--model`.** The configured default, `gemini-3.6-flash`, has a 20-requests-per-day free
tier and one claim uses 6–11 requests. The lite model has a larger allowance. A paid key removes
the issue.

### What you should see

```
claim CLM-2026-00601  policy MOT-2025-0021  motor  loss date 2026-03-31
in force on loss date : True  — loss date falls inside the in-force window 2025-10-01 to 2026-09-30
wording to weigh (resolved against the loss date):
  [relevant] PW-MOTOR-001 v5.1 (effective 2025-04-01) — … 2.2 Compulsory deductible [resolved against loss date 2026-03-31]
three numbers, kept separate:
  deductible   : 1000  (PW-MOTOR-001 v5.1)
  sub-limit    : tyre_replacement_when_vehicle_also_damaged = 50  (PW-MOTOR-001 v5.1)
  policy limit : 600000 (IDV)
REFERRED TO ADJUSTER (REF-…): …
decision: none — this system does not state a coverage decision
trace cap_…  |  7 laps, … tokens, $0.00…, …s  |  guard: …
```

That claim is a deliberate test: the loss is on **2026-03-31**, the day *before* endorsement
END-2026-01 raised the compulsory deductible. The correct figure is the old one (1,000), cited to
the base policy, not the endorsement. Run `CLM-2026-00602` (loss on 2026-04-01) and you should
get 1,500 and a citation to the endorsement.

Lines from the model's own prose can differ run to run; the version, dates and numbers come from
tool results and do not.

### Follow one request across every hop

The last line of `triage` prints a trace id.

```bash
./.venv/bin/python cli.py trace cap_<id from your run>
```

You get one table: host LLM laps, each tool call, and the matching span written by the MCP server
**process**, joined by the same id, plus a hop check (`trace id survived every hop: True`).

### Other claims to try

| Claim | Why it is interesting |
|---|---|
| `CLM-2026-00601` / `00602` | loss the day before / the day of an endorsement taking effect |
| `CLM-2026-00603` | policy lapsed before the loss — no wording, no numbers, referral says why |
| `CLM-2026-00604` | loss before the policy started |
| `CLM-2026-00605` | narrative full of names, address, phone and injuries — none may reach logs |
| `CLM-2026-00606` | tyre sub-limit **and** deductible **and** policy limit all matter |
| `CLM-2026-00607` / `00608` | health co-payment the day before / the day of its endorsement |
| `CLM-2026-00418` … `00584` | the 27 claim files from Week 6 |

---

## 2. Check it without a model

These need no API key and run in seconds.

```bash
./.venv/bin/python -m pytest tests/test_in_force_hits.py tests/test_redact_claimant.py tests/test_registry_limits.py tests/test_triage_guard.py tests/test_triage_agent_logic.py tests/test_cap_assertions.py tests/test_wording_versions.py tests/test_cap_trajectory_eval.py tests/test_triage_provider_outage.py tests/test_cap_judge_harness.py tests/test_straddle_cases.py tests/test_no_policy_wording_in_prompts.py tests/test_triage_exclusions_gate.py tests/test_capstone_chunking.py -q
```

Expect `163 passed` (the straddle tests load the index and take a couple of minutes). The assertion tests are built so each check can **fail**: every eval
assertion has a hand-broken input that it must reject.

Retrieval-level before/after for the loss-date filter (needs the index, no model):

```bash
./.venv/bin/python eval/version_check.py
```

## 3. Run the evals (needs a key)

```bash
./.venv/bin/python eval/run_capstone_eval.py --model gemini-3.5-flash-lite --label capstone-eval-vN --out eval/capstone_results_vN.json
```

36 claims, 9 deterministic assertions per case, checkpointed to the `--out` file; add `--resume`
after a crash or quota stop. Then, offline from the saved traces:

```bash
./.venv/bin/python eval/rescore_capstone.py <raw results file> --out <new file>
./.venv/bin/python eval/cap_trajectory_eval.py --label capstone-eval-vN --results eval/capstone_results_vN.json
```

---

## 4. Where things live

| Path | What |
|---|---|
| `cli.py` | entry point: `triage`, `trace` (plus the earlier `ingest`, `ask`, `status`) |
| `src/agent/triage_agent.py` | the hand-built agent loop: prompt, budgets, gate, guard, packet |
| `src/mcp_servers/wording_server.py` | **our own** MCP server: `search_wording` (loss-date-aware) |
| `src/mcp_servers/claims_cap_server.py` | MCP server the agent **consumes**: `lookup_policy`, `check_in_force`, `get_limits`, `refer_to_adjuster` |
| `mcp_config_capstone.json` | which servers the agent starts; tools are discovered at run time |
| `src/retriever.py`, `src/wording_versions.py` | retrieval, date/product filter, amended-clause marking |
| `src/triage_guard.py` | the check that stops an outcome statement leaving the system |
| `src/redact.py`, `src/span_log.py` | PII scrubbing and the shared trace/span log |
| `src/cap_assertions.py`, `eval/` | integrated eval, rescoring, trajectory eval |
| `registry/` | **synthetic** policy registry, limits table, nine added claim files |
| `corpora/insurance/` | policy wording + three endorsements |
| `traces/` | `capstone_traces.jsonl`, `capstone_mcp_spans.jsonl`, `referrals.jsonl` |
| `SEAMS.md` | every seam found while integrating, with date, status and evidence |

## 5. If something goes wrong

| Symptom | Cause / fix |
|---|---|
| `Gemini quota exceeded (429)` | free-tier cap. Use `--model gemini-3.5-flash-lite`, wait for the reset, or use a paid key. A run in this state stops after 240 s per claim with 0 tokens. |
| `no such claim` | claim numbers are `CLM-2026-00xxx` (or the older `C-0xx`). |
| `collection not found` / empty search | you skipped `cli.py --strategy structured ingest` (the capstone's index). |
| first run takes minutes | the models are downloading (once). |
| `fastembed` install fails | you are on Python 3.14. Use 3.13. |

## 6. Limits you should know about

- **Synthetic data.** The policy registry (47 policies), the nine added claim files, the limits
  table and every person/address are invented. Real in-force windows and limits would come from
  the client's system.
- **The compliance guard is a pattern check.** It catches stated outcomes ("is covered",
  "payable", "declined") and replaces them; a sufficiently odd paraphrase could pass. Its pass
  rate is 100% *by construction*, so the honest measure is how often the model **tried** to state
  an outcome — reported in the eval, not here.
- **PII scrubbing is pattern-based** (cue words, an injury word list, address and PIN-code
  shapes). It was tested on the nine added claims and a handful of invented FNOLs. It is not a
  guarantee on real claim text.
- **The claimant's narrative is scrubbed before the model sees it**, but the scrubber's gaps are
  the model provider's exposure too.
- **One model, one corpus.** Everything above was run on a single lite model and 7 documents.

Further documents: [ARCHITECTURE.md](ARCHITECTURE.md) (one page), [SEAMS.md](SEAMS.md) (what broke
when the weeks were joined), and the per-week notes `WEEK6.md` … `WEEK11.md`. The Week 3 RAG guide
is still [README.md](README.md).
