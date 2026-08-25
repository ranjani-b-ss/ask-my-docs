# Failure taxonomy — claims assistant

**Sample:** 20 traces, seeded random draw (`seed=20260826`) from 114 real traces.
**Read:** by hand, one observation sentence each, before any category existed. See `notes.md`.
**Ranked by:** frequency × severity. Severity asks one question — can this cost or save money
on a claim that should have gone the other way?

| # | Failure mode | Count | % of 20 | Severity | Example |
|---|---|---|---|---|---|
| 1 | **Refuses a question whose answer is in the passages it just retrieved** — the clause is in the context window, scored highly, and the reply is still "that isn't covered in the documents I have" | 5 | 25% | **Wrongly denies or wrongly pays** — the adjuster is told the policy is silent on a point the policy actually decides | `tr_eeff25a3bea3` |
| 2 | **Gives the headline figure and drops the condition that limits it** — the number is right and correctly cited, but the eligibility test printed in the same passage is left out | 3 | 15% | **Wrongly pays** — a confident, cited answer that overstates cover | `tr_10376875b164` |
| 3 | **Fills every slot from one wrong document and never retrieves the clause that exists** — all five passages come from one unrelated document while the answering clause sits unretrieved in the corpus | 3 | 15% | Annoys the adjuster — refusal, nothing false stated, claim stalls | `tr_297f38675314` |
| 4 | **Shows the corpus's own placeholder banner as a policy source** — the "PLACEHOLDER CORPUS … states no real policy terms" front matter is indexed, retrieved, and in one case cited to the user | 2 | 10% | Annoys the adjuster — destroys trust in every citation on the page | `tr_1b2dd5957cd0` |
| 5 | **Serves a PDF table as a run of one-line headings** — the annexure of non-payable items arrives as `### 2. Hand Wash`, `### 3. Shoe Cover`, one row per heading, with the table's meaning gone | 1 | 5% | **Wrongly pays** — the list of items that are *not* payable is the one list that must survive intact | `tr_9d2e1d93e6d3` |
| — | *No failure observed* — answered correctly and completely, or correctly refused a question the corpus genuinely does not cover | 7 | 35% | — | `tr_34d34d4ae3cf` |

Counts are mutually exclusive and sum to 20. Where a trace showed more than one problem it is
counted once, under the failure the user would actually experience.

## Fix order

Mode 1 first: it is the largest bucket, it fires on questions the corpus *can* answer, and its
cause sits after retrieval — the passages were already on screen — so it is the cheapest of the
five to attack. Mode 2 is smaller but more dangerous per occurrence, and is the same layer, so
one prompt change plausibly moves both.

Mode 5 rests on a single trace. Its frequency is not reliable at n=1 and it is ranked on
severity, not on the 5%.

## The prediction (see `notes.md` for the committed version)

> Dated 26 August 2026, before any fix. Revising the answer prompt to `claims-v2` — requiring
> the model to report a partial answer or a deferral instead of refusing, and to state what the
> passages *do* say whenever it declines — will drop **mode 1 from 25% (5/20) to 10% or less
> (≤2/20)** on these same 20 traces, and will not turn any of the 7 currently-clean traces into
> a false answer.

Falsifiable two ways: if mode 1 lands above 10%, the prompt was not the cause. If a clean trace
starts answering a question the corpus cannot support, the change traded a refusal for a
fabrication and must be reverted.
