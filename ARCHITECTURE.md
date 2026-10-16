# Architecture — Claims Triage & Coverage Assistant

One request: **claim number in → referral packet out**, one trace id from start to finish.

```
 python cli.py triage CLM-2026-00601
        │
        ▼
┌─ HOST ─ src/agent/triage_agent.py ─ hand-built Thought/Action/Observation loop ─────────────┐
│                                                                                             │
│  claim narrative ──scrub_claimant──▶ model (Gemini)            budgets: 12 laps, 30k tokens,│
│  (names, address, injuries removed                             $0.03, 240 s wall            │
│   BEFORE the model sees it)                                                                 │
│                                                                                             │
│  model says: Action + JSON args                                                             │
│        │                                                                                    │
│        ▼  ① GATE        tool order enforced (lookup → in-force → search → limits → refer)   │
│        ▼  ② OVERWRITE   claim_number, policy_number, loss_date, product set by the host,     │
│        ▼                never taken from the model                                          │
│        ▼  ③ GUARD       outcome statements in the referral text are replaced and counted    │
│        ▼  ④ TRACE ID    injected into every call, hidden from the model                     │
│                                                                                             │
│  tools are DISCOVERED at run time from the servers (MCPToolRegistry), not hard-coded        │
└──────────────────────────────┬──────────────────────────────────────────────────────────────┘
                               │  MCP over stdio (two server processes)
            ┌──────────────────┴───────────────────┐
            ▼                                      ▼
┌─ claims-system (consumed) ───────────┐  ┌─ policy-wording (our own) ──────────────────────┐
│ claims_cap_server.py                 │  │ wording_server.py                               │
│  lookup_policy    → policy, product, │  │  search_wording(query, product, loss_date)      │
│                     LOSS DATE        │  │    │                                            │
│  check_in_force   → window check     │  │    ▼ vector search + BM25 → fuse (RRF)          │
│  get_limits       → deductible/      │  │    ▼ DATE + PRODUCT FILTER  (code, not prompt)  │
│                     co-pay, sub-     │  │    ▼ cross-encoder rerank                       │
│                     limits, policy   │  │    ▼ mark clauses an in-force endorsement       │
│                     limit (3 numbers)│  │      amended  (superseded_by)                   │
│  refer_to_adjuster→ writes referral  │  │  returns chunks with document, version,         │
│                                      │  │  effective date, clause, chunk id               │
│ registry/ (synthetic)                │  │ corpora/insurance/ + structured .chroma index   │
└──────────────────┬───────────────────┘  └──────────────────┬──────────────────────────────┘
                   │ each server process writes its own span, same trace id
                   ▼                                         ▼
          traces/capstone_mcp_spans.jsonl            (both through span_log.append,
          traces/referrals.jsonl                      which scrubs claimant text on write)
                               │
HOST ◀── tool results ─────────┘
   │
   ▼  ⑤ PACKET   cited chunks must have been retrieved THIS run; version and effective date are
   │             copied from the chunk, not from the model; superseded clauses dropped;
   │             `decision` is always null; unresolved numbers flagged by code;
   │             a run that ends without a referral gets a forced one, even if the model
   │             provider is down (SEAMS.md S15; fixed, tested with a stub provider)
   ▼
 traces/capstone_traces.jsonl  ──  python cli.py trace <id>  stitches host + both servers
```

## What is enforced in code, and what is only asked for

The brief's compliance rule is the reason this table exists. A prompt can be ignored; these cannot.

| Rule | Enforced by | Only asked in the prompt |
|---|---|---|
| Wording is the version in force on the **loss** date | `in_force_hits()` removes later-dated chunks before the model sees any | — |
| Loss date and product are right | host overwrites the model's arguments and records each override | "use the loss date from lookup_policy" |
| Amended clause is not cited next to its replacement | retrieval marks `superseded_by`; packet builder drops it | "cite the endorsement's clause" |
| Citation names document + version + date | copied from chunk metadata at packet build | — |
| Only cite what was retrieved | chunk ids checked against this run's retrievals | — |
| Never state a coverage decision | `triage_guard` replaces it in the final answer **and** in the referral arguments; `decision` is `null` | "never write covered/payable/declined" |
| Deductible, sub-limit, policy limit are three numbers | `get_limits` returns them as separate fields; packet never merges | — |
| Unresolved number is surfaced | host adds an `unresolved:*` flag to the referral | — |
| Refer to an adjuster | tool order gate + forced referral at loop end | — |
| The exclusion list was actually read | host gate: no referral until a retrieved chunk is the "What is not covered" section (names no wording) | the section title, once, in the prompt |
| What to search for | — | the prompt (exclusion phrasing, one or more searches) |
| Which facts to extract from the narrative | — | the prompt |

The last two rows are where the model's quality still shows, and where the eval looks for failures.

## Data and trust boundaries

```
claimant text ─▶ scrub_claimant ─▶ model          (the model sees facts, not people)
                                └▶ logs           (re-scrubbed on every write)
claim / policy numbers: kept in logs on purpose (an adjuster must be able to find the file)
generated ids (trace_id, referral_id, chunk_id…): never scrubbed (S14 — scrubbing them broke tracing)
policy wording: public to the model, never redacted
```

The scrubber is pattern-based. It is a control, not a guarantee.

## Shape of one run (typical)

7–11 model laps · 5 tool calls · 2 MCP processes · ~15–30k tokens · about $0.004 · 10–60 s.
Every number here is from the first integrated run; the final figures are in the eval report.
