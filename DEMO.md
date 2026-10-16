# 10-minute demo script

Four parts, one clock. Say the **bold** lines; do the `commands`. Times are cumulative.
Rule from the brief: *a flawless demo is a red flag* — Part 2 shows real failures and Part 4 shows
how I know they stay fixed.

> **Prompt version (2026-10-14).** Most numbers in this script were measured under `triage-v2`, whose prompt quoted exclusion wording (SEAMS.md S21).
> The live run uses `triage-v3` + structured chunking + the exclusions gate, whose 36-case result is **32/36 = 89%** (EVAL_REPORT.md §10) — say that, not 97%.
> Do not present CLM-2026-00567 (parser loop) or 00606/00607 (token budget) as clean. The taxonomy and judge numbers are still v1/v2.

## Before you start (5 minutes, not on the clock)

1. `cd ask-my-docs`, venv present, `.env` has `LLM_PROVIDER=gemini` and a key.
2. **Check quota first** with one tiny call (the run uses ~7 requests per claim; the free tier ran out
   after 454 requests on 2026-10-09). No quota → use the recorded traces below and say so.
3. Warm up once, off the clock, so the servers' models are cached:
   `./.venv/bin/python cli.py triage CLM-2026-00601 --model gemini-3.5-flash-lite`
4. Two terminals side by side: one for `triage`, one for `trace`. Font large.
5. Open `SEAMS.md`, `EVAL_REPORT.md`, `WEAKNESSES.md`, `10X_PLAN.md` in tabs.

**Recorded fallbacks** (all real, in `traces/capstone_traces.jsonl`):
`cap_fde18a29a98e` = CLM-2026-00601 on the final system · `cap_3ecd0e89505f` = 00602 final ·
`cap_3e24c30439a3` = 00602 before the fix · `cap_b9a5a5916417` = a claim lost to the outage.

## Part 1 — a real run (0:00–3:30)

**0:00 "This takes a claim number and returns a referral packet for an adjuster. It never says
whether a claim is covered — `decision` is always null, and I'll show the assertion, not the prompt."**

**0:30** Run, narrate while it works (~30 s):
`./.venv/bin/python cli.py triage CLM-2026-00601 --model gemini-3.5-flash-lite`

**"The loss is dated 31 March 2026 — the day *before* an endorsement raised the compulsory deductible.
Watch for three things."** Point at the output:
1. `in force on loss date: True` and the window — **"a tool call, not the model's opinion."**
2. The citation: `PW-MOTOR-001 v5.1 (effective 2025-04-01) … [resolved against loss date 2026-03-31]`
   — **"document, version, effective date, and the date it was resolved against."**
3. The three numbers — **"deductible 1,000, tyre sub-limit 50%, policy limit 600,000 IDV — separate
   fields, each tied to a document and version."** Then `REFERRED TO ADJUSTER` and
   `decision: none`. **If a `refer_to_adjuster BLOCKED` line appears in the trace, leave it in:** the model tried to refer before searching, the gate refused, it recovered — that is the gate working, and 5 of 36 runs did it.

**2:00 "Now the same claim one day later."** `… cli.py triage CLM-2026-00602 …`
**"Loss on 1 April: deductible 1,500, cited to END-2026-01. Same code, one day apart, different
figure and different citation — and the old clause is not cited next to it."**

**3:00** Trace: `./.venv/bin/python cli.py trace <id from the run>`
**"One trace id across the host, the claims server and the wording server — two other processes —
and `trace id survived every hop: True`. Each hop has latency and cost."**

## Part 2 — the failures I found (3:30–6:30)

**3:30 The top mode: citing both the amended and the superseded clause.**
`./.venv/bin/python cli.py trace cap_3e24c30439a3`
**"CLM-2026-00602 on my first integrated run: it cited the base-policy deductible clause *and* the
endorsement that replaced it — two figures, 1,000 and 1,500, in front of the adjuster. 8 of 36 cases
did this. My date filter had already removed endorsements not yet in force; it could not remove a
clause that was in force but amended. My Week 6 suite could not see this at all (SEAMS S2, S6)."**

**4:45 The mode integration created.**
**"No single week's tests would have found this. The agent's tool block showed the model the raw
JSON schema, so it copied `{"type": "room rent"}` into the `query` argument. 17 rejected search calls
in 17 of 36 cases; some hit the token budget (S10)."** Show the error text (the trace table does not flag failed calls):
`./.venv/bin/python -c "import json;[print(s['error'][:200]) for l in open('traces/capstone_traces.jsonl') for r in [json.loads(l)] if r['trace_id']=='cap_9fd6b2e632ce' for s in r['spans'] if s.get('ok') is False]"`
**"And a second one the seams created: when the model provider ran out of quota, 9 claims finished
with no referral at all — the backstop only fired after the loss date was known (S15)."**
Show `cli.py trace cap_b9a5a5916417`: **"0 tokens, two laps of 120 seconds each, no tool ever called — and `survived every hop: False` is correct here, because nothing reached a server. Nothing in the adjuster queue."**

**5:45 The two weaknesses I wrote down** (`WEAKNESSES.md`, dated honestly — written after the eval):
**"One: I prove the right *version*, not the right *clause*, and my citation labels can mislead — CLM-2026-00606's
citation reads 'No Claim Bonus protection' but the tyre limit it relies on is in that chunk's second section, because
I label a chunk by its first heading; 16 of 59 chunks hold more than one. Only 6 of my 36 cases carry citation gold. Two: the compliance guard
and the PII scrubber are pattern checks — the model *tried* to state an outcome in 13 of 36 cases, the
guard stopped every one, but that zero is true by construction, so I cannot tell you what a new
phrasing would do. Three, from the brief's regulator question: I can't yet replay an agent answer
byte for byte."**

**Taxonomy** (`taxonomy_w12.md`, 72 runs read by hand): **"I read all 72 runs. Seven modes. Four are new from joining the pieces —
the schema-echo tool error (17 → 0), the unflagged missing number (4 → 0), the guard blanking the summary (6 → 6), and the
citation label that shows a chunk's first heading (5 → 4). The punchline: my final run passes 35 of 36 assertions, but 13 of 36
runs still show a mode — and 12 of those 13 passed every assertion. The suite only sees what I wrote it to see."**

## Part 3 — a number that moved (6:30–8:30)

**6:30 "Wrong-version citation rate: 8 of 36, 22%, before; 0 of 36 after. n is 36 and the interval on
the after figure is 0 to 10% — I can't claim zero."** Show `EVAL_REPORT.md` §1.

**7:15 "Your hostile question — cases with a loss date between two versions: five. Before: 3 of 5.
After: 5 of 5. Not the average — those cases."** (§3)

**7:45 "What I changed after seeing the result:** one assertion rejected 'in-force window' because of a
hyphen; I fixed it, kept the as-run score — 33 of 36 — next to the corrected 35 of 36."**

**8:10 "The judge's agreement with my hand labels on these outputs: 94% pooled over 70, 97% on the held-out half — and I will
tell you why that number is nearly worthless: only 3 of 70 outputs are actually wrong, so a judge that always says 'grounded'
scores 96–97%. Chance-corrected, kappa is 0.4 to 0.6. It caught all 3 real errors — which every one of my nine assertions had
passed — but only 3 of its 7 alarms were real. My labels are not independent and one was corrected after I saw the judge."** (§8)

**8:20 "What the suite doesn't measure at all: whether the cited clause answers the question — only
that it is the right version."**

## Part 4 — what's next (8:30–10:00)

**8:30 "The permanent guard."** `./.venv/bin/python -m pytest tests/test_triage_provider_outage.py tests/test_cap_assertions.py -q`
**"The outage fix has a test that starts with a provider that always fails and asserts one referral;
it was red — 'expected exactly one referral, got 0' — before the fix. The superseded-clause failure is
guarded by an assertion that can fail and by five boundary cases in the suite."**

**9:00 "Cost: $0.0036 per claim, about 25 seconds, 7.4 model calls."**

**9:20 "A hailstorm week — 18,000 claims — what breaks first: the model provider's quota, at about
claim 61. The free tier took 454 requests and then returned 429; clearing 18,000 claims takes 46
requests and 138k tokens a minute if half arrive in the first day. Second, claims silently lost in
the outage — that's the bug I just fixed. Third, the runner is serial: 119 claims an hour."**
(`10X_PLAN.md`) **"What does *not* break: the MCP hop at 7% of its ceiling, and cost at $68."**

**9:50 "Everything uncertain is marked pending. Questions."**

## If it goes wrong live

- **429 or slow model:** *"That is the failure from Part 2."* Run `cli.py trace cap_b9a5a5916417`
  and carry on from the recorded runs.
- **Wrong or odd citation on the live claim:** read it out. A live failure on the right claim is the demo.
- **First run slow (>60 s):** the servers are loading models; narrate Part 1's framing meanwhile.

## Hostile questions — where the answer is

| Question | Show |
|---|---|
| 2024 loss, 2025 exclusion — how many straddle cases, what do *they* score? | `EVAL_REPORT.md` §3 |
| "It said covered and we paid" — who is liable; does it ever say covered? | `tests/test_triage_guard.py`, `src/cap_assertions.py::never_states_coverage`; **and** `WEAKNESSES.md` #2 |
| Three numbers — the trace and the assertion | 00601 trace; `numbers_distinct_and_correct` |
| Reproduce a declined claim eighteen months on | **Honest answer: partly** — `WEAKNESSES.md` #3 |
| What is in the logs; what did the MCP server hand over? | `traces/*.jsonl`; `src/redact.py`; PII case CLM-2026-00605 — and `WEAKNESSES.md` #2 for what it can't promise |
