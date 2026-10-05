# Week 11 — the support drill

**Complaint, verbatim as given**: "an adjuster says it told a claimant something was
covered when the policy excludes it, sometime yesterday." No trace id, no claim number, no
timestamp.

## Methodology, disclosed honestly

**This drill was not blind, and no squadmate timed it.** There is no squadmate on this solo
build; I built the scenario myself, and I had already read the full C-011 trace — including
its Final Answer — before I started the timer. The submission checklist's "timed by a named
squadmate" is not met, and the time reported below is not a blind time.

What is real: I added one new claim (C-011, probing an exclusion bullet — "outside the
geographical area stated in the schedule" — that no prior claim in this project ever
exercised). A zero-LLM retrieval test first showed natural phrasings of "accident abroad"
missed that clause, so I expected a failure. I then ran C-011 by hand four times (all ended
`REFERRED` on token, wall-clock or quota budgets, none with a clean answer) and then the
real suite (`eval/run_claim_suite.py`, 11 claims, real `react_agent.run()` calls, real
Gemini responses). The failure itself was live and unscripted, and the "covered ... no
policy exclusions apply" Final Answer first appeared in the suite run — but it was
predicted, not blind.

## Time to find: **00:45**, by full-text content search — not blind, not squadmate-timed

The 45 seconds (`date +%s.%N` before and after, 45.05s) covers exactly these commands, in
this order, and nothing else:

1. **Naive attempt (the one the brief warns about)**: searched top-level `status=="PAYABLE"`
   rows for `rationale` containing "covered" — the complaint's literal wording.
   **3 false-positive hits** (C-001, C-002, C-008 — all genuinely, correctly payable). The
   actual bad trace's top-level status is `REFERRED`, not `PAYABLE`, so this search missed
   it entirely — exactly the brief's own warning: searching only the field the complaint
   names in isolation isn't enough.
2. **Broadened to non-PAYABLE rows**: full JSON of every non-PAYABLE row from the day,
   filtered for "covered" and "exclu" — 9 candidates, too many to read as-is.
3. **An exact-phrase query**, `"no policy exclusions apply"` — 1 match, the right trace.
   *This phrase was hindsight:* I only knew it because I had already read the trace. A
   blind investigator could not have run this query.
4. **A scan of those 9 candidates' step-level Final Answer rationales** for a sentence that
   positively asserts coverage — also 1 match, the same trace, without needing step 3's
   phrase. Still shaped by what I'd already read, but less dependent on it. The timer
   stopped here.

**The slice that found it was a content search over nested step output.** That is not one
of the five listed slices (time / user / prompt version / input type / cost outlier). Read
the 45 seconds as a lower bound, not a measurement of how long a blind find takes.

**The cost-outlier slice was run afterwards, untimed**, as a check: sorting the day's real
traces by `usage.cost_usd` descending puts the bad trace **#1 of the 11 real runs in that
pass** — $0.00609, more than 4x the cheapest. (A 12th row from an aborted, rate-limited
attempt cost $0 and is excluded.) So of the five listed slices, cost-outlier is the one that
*would* have surfaced it near-instantly — but I did not time that path.

The other slices: **time** and **user** (`submitted_by`) alone did not narrow usefully (16
real rows share today's date; this claim's submitter also filed others). **prompt_version**
didn't help *this* time (only one version existed at that point — it becomes the
discriminator for every future regression, now that v2 exists). **input_type** isn't a
field this app tracks at all — it serves exactly one request shape (motor claim triage) —
and I did not add it.

## What was actually found — more than the complaint described

The complaint's shape ("it said covered, should have excluded it") matches the real
finding, but the *mechanism* is more specific and more concerning than a simple missed
exclusion — see `trace.json`'s `_annotations` and the full step-by-step reasoning:

1. **A real, confirmed retrieval gap.** The exclusion-list clause (`PW-MOTOR-001`, "3. What
   is not covered") is one list of 7 bullets split across two overlapping chunks by the
   chunker: `PW-MOTOR-001::4` holds 6 of them, `PW-MOTOR-001::5` holds only the 7th and
   shortest — "loss or damage occurring outside the geographical area stated in the
   schedule." Every one of the agent's 6 real search queries (laps 2-7, see `trace.json`)
   retrieved `::4` or unrelated chunks (mostly health-policy endorsements), and **never once
   retrieved `::5`** — confirmed
   directly from the logged `retrieved_chunk_ids`, not inferred. A literal query for
   "outside the geographical area stated in the schedule" retrieves `::5` at 0.9988
   relevance, rank 1 — the chunk is reachable, just not by any phrasing the model actually
   tried.
2. **A hallucination this repo hasn't documented before.** After three failed searches
   (laps 2-4), the model's own `raw_output` on laps 5-7 contains *fabricated* clause text
   embedded inside its own Thought/Action turn — a fictional "Endorsement 1 Clause 4 —
   accidents in Nepal or Bhutan are covered without requiring a special extension
   endorsement" that does not exist in the corpus: a case-insensitive grep for
   `nepal|bhutan|kathmandu` across all of `corpora/` returns nothing. The model invented a
   convenient, claim-favorable exception and then cited it as real in its Final Answer. This is a *second*, distinct
   failure mode layered on top of the retrieval gap, and it's the more dangerous one: a
   confident, specific, entirely fictional citation.
3. **A methodology caveat, stated plainly**: this run used `gemini-3.5-flash-lite`, not the
   project's pinned `gemini-3.6-flash` — the pinned model's 20-requests-PER-DAY free tier
   was exhausted again today before the suite ran (see `tenx.md`), partly by my own four
   hand-run C-011 attempts described in the methodology section. The
   hallucination in particular may be more a property of the weaker substitute model than
   of the architecture itself; I did not get to test whether the pinned model does the same
   thing under the same retrieval gap, because its quota was already spent. The retrieval
   gap (§1) is independent of model choice — confirmed with a zero-LLM-cost retrieval-only
   test before any live run.

## Bonus — not attempted

The bonus (add the missing field, have a second bad answer planted, beat the first time)
was not done: it needs a second live run, and this key's daily quota was spent.

Two notes on log fields, stated plainly:
- **`retrieved_chunk_ids`** was added to the trace schema *before* the drill, because the
  brief's common-mistake #6 names it — its absence did not cost time in this drill. What it
  did make possible is finding 1 above (confirming `::5` was never retrieved across 6
  tries), which would otherwise have been a guess rather than a fact.
- **`input_type`** is the field still missing. This app serves exactly one request shape,
  so there was nothing to index yet; it was not added, and no field was added in response to
  this drill.
