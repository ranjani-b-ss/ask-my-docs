# Week 12 handoff — what is done, what is not, and how to finish it

Written 2026-10-15. Capstone: **Variant D — Claims Triage & Coverage Assistant** (RAG + hand-built agent + MCP, consumed and own
server + eval suite + logging + the 10× plan). Branch `week-12-capstone`. Read `CAPSTONE.md` (how to run) and `ARCHITECTURE.md` (one page)
first; this file is only the *state* and the *to-do*.

## 1. Where it stands, in one paragraph

The system works end to end (`python cli.py triage CLM-2026-00601`), the offline test suite is green (**282 tests**; the capstone's own list in
`CAPSTONE.md` is 163), and most deliverables exist as files. What is **not** done is mostly *re-measurement*: the system changed three times after
the main evals were run (prompt wording removed, `structured` chunking, an exclusions gate, a parser fix), and the Gemini free-tier quota has
repeatedly run out, so the final-code 36-case run was only completed late: **33/36 = 92%** with the parser fix (v3 before it: 32/36). Two deliverables need a human (fresh-eyes note, demo on a clock).

## 2. Status by deliverable

| Brief item | State | Evidence |
|---|---|---|
| Single entry point + README a stranger can follow | **Written, never run cold** | `CAPSTONE.md`; fresh-eyes check not done |
| Seam list (unedited, dated) | Done, append-only | `SEAMS.md` S1–S23 |
| One-page architecture sketch | Done (a little over a page) | `ARCHITECTURE.md` |
| Eval suite, 25–40 cases, assertions before judge | Done: 36 cases, 9 deterministic assertions | `src/cap_assertions.py`, `eval/run_capstone_eval.py` |
| Judge, validated ≥85% vs hand labels | Done **on v1/v2 outputs**; not on the final system | `EVAL_REPORT.md` §8 |
| Error taxonomy re-scored, 4–7 modes, ≥1 new | Done on v1, v2 **and the final system v3b** (2026-10-16; R8 added) | `taxonomy_w12.md` (+ `_notes.md`) |
| Trajectory eval, 10+ cases | Done; scored for v1, v2, v3 | `eval/cap_trajectory_eval.py` |
| One trace id across agent + MCP hops, PII out | Done | `cli.py trace <id>`; `src/span_log.py`, `src/redact.py` |
| Closed failure→test loop | Done (S15 outage → test; S12/S14 etc.) | `tests/test_triage_provider_outage.py` |
| Cost per claim + 10× plan | Done | `10X_PLAN.md` ($0.0044/claim now; quota breaks first) |
| Eval report with stated non-coverage | Done (draft status removed once P2 is re-run) — §7 written | `EVAL_REPORT.md` |
| Top-3 weaknesses, dated honestly | Done (written after the eval, says so) | `WEAKNESSES.md` — needs a v3 refresh |
| 10-minute demo script | Done, **never rehearsed**; numbers partly stale | `DEMO.md` |
| Fresh-eyes note | **Not done — needs a person** | — |
| Bonus: loss-date retrieval, 5 straddle cases red→green, hit@3 cost | Done | `STRADDLE_BONUS.md` |

## 3. Pending tasks, in the order I would do them

### P1 — ~~Finish the 36-case run for the final code~~  **DONE 2026-10-18**
`eval/capstone_results_v3b.json` now holds all 36 valid rows: **33/36 = 92%** (v3 before the parser fix 32/36; v2 35/36). Three fail: 00468 (token budget → no numbers),
00491 and 00584 (S17 amendment map). One run per case, so v3 → v3b is within noise. 6 runs stopped on the token budget and 5 of them still passed every assertion — the suite
does not see an unfinished packet. Written up in `EVAL_REPORT.md` §10b and `SEAMS.md` S21–S23. The trajectory eval was repeated (`eval/cap_trajectory_v3b.json`: 21/36 clean routes, 93.1% tool choice).
If you want a variance estimate, run it again with a new `--label`/`--out`; the quota allowed one full pass per day.

### P2 — Re-score the final system  *(offline once P1 is done, except the labels)*
- **Trajectory:** done for v3b (`eval/cap_trajectory_v3b.json`).
- **Taxonomy:** done for v3b (`taxonomy_w12.md`, `eval/taxonomy_w12.py` now covers v1/v2/v3b; 36 observation sentences in the notes). Open from it: R8 (unresolved co-payment unflagged, 13 of 36) needs `unresolved_flags` extended beyond the deductible; R5 is half guard-matches-a-clause-title; R4 is driven by the gate's extra search (S23).
- **Judge:** the 70 frozen labels cover v1/v2 only. Either hand-label the ~36 new outputs (protocol: `eval/judge_cap_protocol.md`; the `ChunkStores` class
  already rebuilds context from whichever index a trace used) and re-run `eval/run_cap_judge.py`, or leave §8 labelled "v1/v2 outputs". Do not edit
  `eval/labels_cap_70.json` — a test checks its hash; record revisions in `labels_cap_70_revisions.json`.

### P3 — ~~Write the non-coverage list~~  **DONE 2026-10-18** (`EVAL_REPORT.md` §7: 13 unmeasured items, 7 weakly measured, 5 measured only on the older system)
Re-read it after P1/P2 if the taxonomy or judge are repeated: tier C shrinks as they are.

### P4 — Fresh-eyes note  *(needs a person; ~1 hour)*
Someone who did not build it clones the repo, follows `CAPSTONE.md` cold, and writes down every place they got stuck. The brief also wants a foreign MCP
client (a stand-in is fine) pointed at the **own** server (`src/mcp_servers/wording_server.py`). Known traps they will hit: the capstone needs the
`structured` index (`cli.py --strategy structured ingest`), the default `ingest` builds a different one; the first run takes ~30 s while servers load models.

### P5 — Demo  *(1 hour + rehearsal)*
Update `DEMO.md` to the P1/P2 numbers (it still quotes v2's 97% in places), replace the "TAXONOMY" and judge lines with final counts, refresh the recorded-trace
fallbacks from v3b, and **rehearse against a clock** — it has never been timed. The first live run may show a `BLOCKED` line (the gate or tool order); leave it in.

### P6 — Open decisions (each is small; none is made)
| Seam | Decision |
|---|---|
| S23 | the 30,000-token budget now binds at the median (28.3k) — raise it, or stop resending every chunk each lap (95% of tokens are prompt) |
| S22 | the missing-marker error message is still empty, so other format slips get no hint; `Final Answer:` must still be spelled exactly |
| S17 | the amendment map misses 5 of 16 amended clauses (e.g. motor intimation, health reimbursement) — fix is "parse every `Amendment to Clause X` heading in the chunk text, not just the section label" |
| S18 | the guard blanks adjuster-facing text (`[withheld …]`) in ~1 run in 5 — try rewriting instead of replacing |
| S19 | nothing stops a second `refer_to_adjuster` (one duplicate seen) |
| S20 | the registry and a claim narrative can disagree on sum insured (CLM-2026-00479) |
| S16 | `prompt_sha` does not cover the tool description |

### P7 — Nice to have
- **Week 12 tab in `trace_viewer.py`** (tabs stop at Week 11; it would read `traces/capstone_traces.jsonl` and show packet + stitched trace + eval results).
- **Straddle end-to-end ablation on the current config** — it ran on the legacy index and `triage-v2`; a second run and the control CLM-2026-00608 were lost to quota
  (`python eval/run_straddle_ablation.py --runs 2`).
- **Week 11:** the 11-claim suite was not re-run on the new chunking/gate (`python eval/run_claim_suite.py --model gemini-3.5-flash-lite`); the C-007/C-011 comparison
  is n=4 per arm.
- **Refresh `WEAKNESSES.md`** with what v3 showed: the model attempts outcome statements twice as often once it sees the full exclusion list (44 vs 22).

## 4. What to trust, and what not to

| Claim | Number | Caveat |
|---|---|---|
| Final-answer pass rate | v1 26/36 (72%) → v2 35/36 (97%) → v3 32/36 (89%) | one run per case; v2→v3 is within noise; **no number for the parser-fixed code** |
| Wrong-version citation rate | 8/36 → 0/36 (95% CI 0–10%) | v1→v2 only; the v2 prompt quoted exclusion wording (S21) |
| Judge vs my labels | pooled 94% (κ 0.42–0.57); held-out 97% (κ 0.65) | 3 of 70 outputs are wrong, so raw agreement ≈ the always-GROUNDED baseline; labels are mine, not independent; same model family as the system |
| Loss-date filter | 7/8 straddle cases red → 0/8; 0 hit@3 lost on 22 control questions | end-to-end: 5/5 exposed → 0/5, 3/5 cited → 0/5, **n=5, one run** |
| Chunk + gate repair (Week 11 C-007/C-011) | 0/4 → 2/4 → 3/4 | n=4 per arm |
| Exclusion reach | governing bullet reaches the model 7/7 (legacy index 5/7) | retrieval only, no model |
| Cost | $0.0044/claim, median 28k tokens | free-tier quota is the first thing that breaks at volume |

## 5. How to pick it up

```bash
cd ask-my-docs && python3.13 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env            # set LLM_PROVIDER=gemini and GEMINI_API_KEY   (.env is gitignored)
./.venv/bin/python cli.py --strategy structured ingest   # the capstone's index
./.venv/bin/python cli.py ingest                         # the LEGACY index — only needed to rebuild/verify old traces
./.venv/bin/python -m pytest tests -q                    # 282 pass (~2 min; some tests load the index)
```
Env switches (all default to the shipped behaviour; they exist only for before/after measurement): `CAPSTONE_CHUNKING` (index slug),
`TRIAGE_EXCLUSIONS_GATE=off`, `AGENT_EXCLUSIONS_GATE=off`, `AGENT_CHUNKING`, `WORDING_DATE_FILTER=off`.
Model: use `--model gemini-3.5-flash-lite` — the pinned `gemini-3.6-flash` has a 20-requests-per-day free tier.

## 6. Things that will bite you

- **Quota.** It is the dominant failure of this week. A run that returns 0 tokens in ~240 s is an outage, not a result. Files named `*_NOT_RESULTS.json` /
  `*_NOT_A_RESULT.json` / `*raw_with_outage*` are set aside on purpose; do not count their rows.
- **Two indexes.** Old traces (no `index` field) were produced on the legacy `recursive` index; `eval/cap_judge.py` rebuilds them from it and checks the stored
  content hash. Two v1 runs cannot be verified (their hashes were corrupted by S14) and are excluded everywhere.
- **Do not reuse filenames from earlier weeks.** While writing Week 12 I overwrote Week 8's `eval/trajectory_eval.py` and its test (and so would have broken
  `trace_viewer.py`). Caught before pushing and restored; the Week 12 version is `eval/cap_trajectory_eval.py`. Check `git status` for `M` on files you did not mean to touch.
- **`DEFAULT_CHUNKING` must stay `recursive`** — every stored Week 3–12 chunk id and hash depends on it (a test pins it).
- **A passing probe means little.** Three tiny calls succeeded minutes before the quota died on every long run.
- **Secrets.** The Gemini key and a Groq key were visible in chat during this work: **rotate both.** The Groq changes are in `stash@{0}` and were never pushed.

## 7. File map (what is new)

`src/`: `triage_agent.py` (loop, gates, packet), `triage_guard.py`, `cap_assertions.py`, `claim_files.py`, `registry.py`, `limits.py`, `span_log.py`,
`wording_versions.py`, `mcp_servers/{wording_server,claims_cap_server}.py`; changed: `retriever.py` (loss-date filter), `chunker.py` (`structured`), `config.py`,
`redact.py`, `agent/react_agent.py` (prompt v3, gate, parser tolerance), `agent/tools.py`.
`eval/`: runners (`run_capstone_eval.py`, `run_cap_judge.py`, `run_straddle_ablation.py`, `rerun_chunk_fix.py`), scorers (`cap_trajectory_eval.py`, `taxonomy_w12.py`,
`cap_judge_agreement.py`, `rescore_capstone.py`), data (`labels_cap_70.json`, `planted_cap.json`, `version_cases.yaml`, `questions_straddle_control.yaml`), results `*.json`.
`registry/` synthetic policies; `traces/capstone_*.jsonl`, `referrals.jsonl`. Docs: `CAPSTONE`, `ARCHITECTURE`, `SEAMS`, `EVAL_REPORT`, `STRADDLE_BONUS`, `10X_PLAN`,
`WEAKNESSES`, `DEMO`, `taxonomy_w12*.md`, this file.

## 8. Rubric map (where the evidence is)

Failure-finding (30): `taxonomy_w12*.md`, `SEAMS.md`, `WEAKNESSES.md`. Number that moved (25): `EVAL_REPORT.md` §1/§10, `STRADDLE_BONUS.md`. Integration (20): `ARCHITECTURE.md`,
`cli.py trace`. Application depth (15): `registry/`, loss-date/version handling, `10X_PLAN.md`. Iteration (10): `SEAMS.md` statuses, the v1→v2→v3 history in `EVAL_REPORT.md`.
