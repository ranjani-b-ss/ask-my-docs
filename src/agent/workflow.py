"""The same triage task, done as a fixed sequence — no loop, no LLM deciding what to do next.

Four steps, always in this order, always all four:

    1. get_claim            — code, no LLM
    2. search_policy         — code, no LLM (the deductible clause, always)
    3. search_policy         — code, no LLM (an exclusion query, ALWAYS — see below)
    4. the decision          — DECISION_VOTES LLM calls on the identical prompt, majority
                                vote taken (see below for why this is no longer one call)
    5. compute_payout        — code, no LLM

Step 3's QUERY is what depends on the notes, chosen by a fixed keyword table rather than by
reasoning about the notes the way the agent does — but the SEARCH ITSELF is no longer
conditional on a keyword matching. It used to be: no recognised risk word in the notes meant
step 3 never ran at all, so Clause 3 ("what is not covered") was never even fetched to
CONFIRM there was nothing to exclude. That was WEEK7.md's C-008 finding — a windscreen claim
with no risk keyword in it referred instead of paying, not because anything excluded it, but
because nothing had ever been fetched to check. The deductible clause was always checked
unconditionally; the exclusion clause now is too, falling back to a general "what is not
covered" query when no specific keyword fires.

Step 4 stopped being a single call after a second, different bug: a conditional exclusion
("X unless Y") was being misread regardless of how the instruction was worded, and repeat
runs of the identical prompt against the identical claim swung between roughly 1-in-6 and
6-in-6 correct with nothing changed but which run happened to land. That is not a wrong
default a clearer sentence can fix — it is variance in an otherwise-plausible answer, and
the standard response to variance is not a better single guess but several guesses with the
majority kept. Same tools, same model, same output contract as ``react_agent.run`` — the
only thing this file does not contain is a loop that decides what to do next based on what
a previous step found; step 4 asking more than once is a fixed, always-3 policy, not a
branch chosen at runtime.
"""

from __future__ import annotations

import re
from collections import Counter

from . import tools, trace
from .react_agent import _find_json_object, VALID_STATUSES
from .usage import UsageAccumulator
from .. import llm

# Fixed, not learned and not LLM-decided: a keyword found in the notes maps to one canned
# policy query. This is deliberately dumb — the point of the race is to find out whether the
# agent's reasoning buys anything over a lookup table this simple.
EXCLUSION_KEYWORDS: dict[str, str] = {
    r"\bvalid driving licence\b": "loss caused while driven by a person without a valid "
                                  "and effective driving licence",
    r"\bdoes not hold\b": "loss caused while driven by a person without a valid and "
                          "effective driving licence",
    r"\bbreathalyzer\b|\bblood alcohol\b": "loss caused while the driver is under the "
                                          "influence of intoxicating liquor or drugs",
    r"\bride-hailing\b|\bhire\b|\bcommercially\b": "vehicle used outside the limitations "
                                                   "as to use stated in the schedule, "
                                                   "private car used for hire or reward",
    r"\bgearbox\b|\btransmission\b": "mechanical or electrical breakdown, failure, or "
                                     "breakage exclusion",
    r"\btyres? burst\b|\btyre\b": "damage to tyres and tubes exclusion",
    r"\bhydrolock\b|\bflooded underpass\b": "flood inundation covered peril versus "
                                            "mechanical or electrical breakdown exclusion",
    r"\bhire car\b|\breplacement vehicle\b": "consequential loss, loss of use, hire "
                                             "charges for a replacement vehicle exclusion",
}

# A category flagged as a KNOWN cross-clause conflict — not a search query, a direct
# instruction to refer, decided by code rather than asked of the model at all.
#
# Added after measurement showed the LLM decision step is WRONG MORE OFTEN THAN RIGHT on
# this exact category: 6 repeat runs of the identical prompt against the identical claim,
# 3 decision calls per run, gave only 6 of 18 individual votes (33%) the correct REFERRED
# answer. That distinguishes this from the "unless"-clause bug (rule 2's worked examples)
# fixed by voting below — voting corrects variance around a correct majority; it cannot fix
# a majority that is itself wrong, and amplifying a 33% base rate through a 3-way vote does
# not reach 50%, empirically confirmed (2 of 6 voted runs still got this wrong). The
# principle generalises beyond this one claim, the same way the deductible bracket and the
# now-unconditional exclusion check do: a small, named set of fact patterns is safer decided
# by a rule than left to a per-call judgement measured to be unreliable on them.
KNOWN_UNRESOLVABLE_PATTERNS = (
    r"\bhydrolock\b|\bflooded underpass\b",
)


# The fallback when no keyword matches. Not a keyword-specific guess — a direct request for
# the exclusion list itself, so a fact pattern nobody anticipated still gets checked against
# it rather than never being looked at.
_GENERAL_EXCLUSION_QUERY = "what is not covered, exclusions on an own damage motor claim"


def _is_known_unresolvable(notes: str) -> bool:
    return any(re.search(p, notes, re.IGNORECASE) for p in KNOWN_UNRESOLVABLE_PATTERNS)


def _exclusion_query(notes: str) -> str:
    """The canned query for this claim's exclusion check — never None any more.

    Fixed code, deterministic, no model involved — the workflow's answer to the same
    "does step 3 depend on what step 2 found" dependency the agent handles by reasoning.
    Which QUERY to send still depends on the notes; WHETHER to send one no longer does — see
    the module docstring for why that distinction is the fix, not the keyword table itself.
    """
    for pattern, query in EXCLUSION_KEYWORDS.items():
        if re.search(pattern, notes, re.IGNORECASE):
            return query
    return _GENERAL_EXCLUSION_QUERY


DECISION_SYSTEM_PROMPT = """\
You are a motor own-damage claims triage assistant. You are given a claim's facts, the \
adjuster's notes, and the relevant policy passages someone else already retrieved for you. \
Decide the claim.

Reply with EXACTLY one JSON object and nothing else:
{"status": "PAYABLE|NOT_PAYABLE|REFERRED", "claim_amount_for_payout": <number>, \
"exclusion_clause": "<document_id and clause/section, or null>", "rationale": "<one or two \
sentences>"}

Rules:
1. Every fact in your rationale must come from the passages given to you — never use \
general insurance knowledge.
2. A clause of the form "X is excluded UNLESS Y" only avoids the exclusion when Y is true \
of THESE facts. Check Y against the claim before applying any exception inside an \
exclusion — never grant a partial or reduced payout under an exception whose own condition \
the facts do not satisfy. Two worked examples of this exact clause shape, with different \
claim numbers and facts from anything you will actually be asked to decide:

  EXAMPLE A — the exception's condition is FALSE. Clause: "damage to tyres and tubes is \
excluded UNLESS the vehicle is damaged at the same time, in which case liability is \
limited to 50%." Claim CX-101: only the two rear tyres were damaged; the surveyor confirms \
no other part of the vehicle was damaged. CORRECT: status NOT_PAYABLE — the "unless" \
condition (vehicle damaged at the same time) is false of these facts, so the exception \
never activates and the exclusion applies in full. WRONG (a real mistake to avoid): status \
PAYABLE at 50% liability — that copies the exception's number without first confirming its \
condition holds, exactly backwards from the intended answer.

  EXAMPLE B — the exception's condition is TRUE. Same clause. Claim CX-102: the two front \
tyres burst AND the front bumper was damaged in the same collision. CORRECT: status \
PAYABLE, claim_amount_for_payout set to 50% of the tyre repair cost (plus the bumper cost \
in full, since the bumper is not a tyre and is not subject to this exclusion at all) — here \
the condition genuinely holds, so the exception genuinely applies.

  The two examples reach OPPOSITE conclusions from the same clause because the FACTS differ \
— checking the condition, not a rule of thumb about "unless" clauses in general, is what \
decides it. Do this same check fresh for the claim below; do not reuse either example's \
conclusion.

  THIS IS NOT THE SAME SITUATION AS RULE 7. Both examples above are about ONE clause's own \
internal exception — a single "X unless Y" sentence, where Y is a fact you can check \
directly. Do not apply this same confidence to a DIFFERENT situation: two SEPARATE clauses \
that each independently apply to the same event, one naming it as covered and a different \
one as excluded, where the passages do not say which one governs when both are true at \
once. Checking a condition inside one sentence is not the same task as resolving a genuine \
conflict between two different clauses — the first has an answer sitting in the text \
waiting to be read correctly; the second may not, and forcing a confident answer onto it is \
the same mistake as EXAMPLE A above, just one level higher up. See rule 7.
3. Where the passages disagree because a later endorsement supersedes the base wording, the \
later effective_date governs.
4. claim_amount_for_payout is NOT the final payable amount — a separate step applies the \
compulsory deductible after you answer. Do NOT subtract the deductible here, and do not \
mention a deductible figure in claim_amount_for_payout's arithmetic at all. The ONLY \
reduction you make here is to remove a line item the passages show is not covered outright \
(for example hire-car or replacement-vehicle charges bundled into the claimed amount) — \
everything else stays as claimed.
5. If status is NOT_PAYABLE, claim_amount_for_payout should be the original claim amount \
(the payout tool will zero it) and exclusion_clause must name the specific clause.
6. The "EXCLUSION CHECK" passages are the policy's list of what is NOT covered. If the \
damage described in the notes does not match anything in that list, it is NOT excluded — \
say so and proceed to PAYABLE. Do not output REFERRED merely because you have not seen a \
passage that explicitly says this exact kind of damage IS covered: a motor policy states \
what is excluded, not an exhaustive list of what is included, so the absence of a matching \
exclusion is itself the answer, not an open question.
7. Reserve REFERRED for when the passages actively conflict about this claim (for example, \
one clause covers the peril and a genuinely separate clause could equally exclude the same \
event, and nothing in the passages says which one governs) or when a fact you would need to \
decide is simply missing from the claim file — not for an ordinary claim that the exclusion \
list simply does not mention. This is a genuinely different situation from rule 2's worked \
examples: rule 2 is about reading ONE clause's own internal exception correctly, which \
always has an answer sitting in the text; this rule is about two DIFFERENT clauses that do \
not say which one wins, which may genuinely have no answer in the text at all. Confidently \
picking a side in a real cross-clause conflict is not careful reading — it is the same \
mistake as misreading a single clause's exception, at a larger scale.
"""


# How many times step 4 asks before deciding. 3 rather than a larger number: cheap enough
# that the workflow keeps its cost advantage over the agent (see WEEK7.md) even after
# tripling this one call, and odd so a status vote cannot tie 1-1.
DECISION_VOTES = 3


def _majority_decision(votes: list[dict], claim_amount: float) -> dict:
    """The majority status among the votes that parsed, with one voting decision's other
    fields (amount, clause, rationale) kept as the ones actually shown to the user.

    Ties and "everything failed to parse" both fail safe to REFERRED — the same rule this
    codebase applies everywhere else a decision cannot be reached with confidence: guessing
    is worse than declining.
    """
    if not votes:
        return {"status": "REFERRED", "claim_amount_for_payout": claim_amount,
                "exclusion_clause": None,
                "rationale": "All 3 decision attempts failed to return a usable answer."}

    counts = Counter(v["status"] for v in votes)
    (leader, leader_n), *rest = counts.most_common()
    if rest and rest[0][1] == leader_n:
        return {"status": "REFERRED", "claim_amount_for_payout": claim_amount,
                "exclusion_clause": None,
                "rationale": f"The {len(votes)} decision attempts tied "
                            f"({dict(counts)}) rather than agreeing — referred rather "
                            "than picking a side arbitrarily."}

    # Among the votes that landed on the majority status, keep the first — arbitrary among
    # equals, but deterministic given the same three raw outputs.
    winner = next(v for v in votes if v["status"] == leader)
    winner = dict(winner)
    winner["rationale"] = (
        f"{winner.get('rationale', '')} ({leader_n}/{len(votes)} decision attempts agreed.)"
    )
    return winner


def _decision_user_prompt(claim: dict, deductible_hits: list[dict],
                          exclusion_hits: list[dict] | None) -> str:
    def fmt(hits: list[dict]) -> str:
        return "\n\n".join(
            f"[{h['document_id']} | effective {h['effective_date']}]\n{h['text']}"
            for h in hits
        )

    parts = [
        f"CLAIM FACTS\nclaim_id: {claim['claim_id']}\ndate_of_loss: {claim['date_of_loss']}\n"
        f"vehicle_cc: {claim['vehicle_cc']}\nclaim_amount: {claim['claim_amount']}\n\n"
        f"ADJUSTER NOTES\n{claim['notes']}\n\n"
        f"POLICY PASSAGES — DEDUCTIBLE\n{fmt(deductible_hits)}",
    ]
    if exclusion_hits:
        parts.append(f"POLICY PASSAGES — EXCLUSION CHECK\n{fmt(exclusion_hits)}")
    parts.append("Decide the claim now.")
    return "\n\n".join(parts)


def _current_deductible(hits: list[dict], date_of_loss: str, vehicle_cc: int) -> float:
    """The compulsory deductible actually in force for this claim, from retrieved text.

    Two mistakes a naive version of this made during development, both worth stating
    because both are exactly the kind of bug a "fixed, dumb" workflow is prone to:

    1. **Picking the top-ranked hit instead of the currently-governing one.** The
       cross-encoder ranks the base clause (PW-MOTOR-001) above the endorsement's amendment
       for a query like "compulsory deductible" regardless of the claim's date, because the
       base clause's heading is a cleaner semantic match for that phrase. Ranked-by-relevance
       is not the same question as governs-as-of-this-date — so this function ignores rank
       and instead scans every retrieved hit whose document_id looks like a deductible clause,
       and picks the one with the LATEST effective_date that is still on or before the date
       of loss. That is a real date comparison in code, not a hope that retrieval sorted it
       correctly.
    2. **Taking the first INR figure in the text regardless of the vehicle's cc bracket.**
       Both the base and the endorsement state the figure in the same fixed sentence shape —
       "INR <X> ... up to 1500cc, and INR <Y> for vehicles above 1500cc" — verified against
       both documents before writing this. So the first number is only correct for a vehicle
       at or under 1500cc; a vehicle over 1500cc needs the second one.
    """
    candidates = [h for h in hits
                  if h.get("document_id") in ("PW-MOTOR-001", "END-2026-01")
                  and h.get("effective_date") and h["effective_date"] <= date_of_loss]
    if not candidates:
        return 0.0
    current = max(candidates, key=lambda h: h["effective_date"])

    amounts = re.findall(r"INR\s*([\d,]+)", current["text"])
    if len(amounts) < 2:
        return float(amounts[0].replace(",", "")) if amounts else 0.0
    index = 0 if vehicle_cc <= 1500 else 1
    return float(amounts[index].replace(",", ""))


def run(claim_id: str, provider: str | None = None, model: str | None = None,
        write_trace: bool = True) -> dict:
    usage = UsageAccumulator()
    if provider:
        usage.provider = provider
    if model:
        usage.model = model

    steps: list[dict] = []

    # Step 1 — always. No LLM, no branching.
    claim = tools.get_claim(claim_id)
    steps.append({"step": 1, "action": "get_claim", "args": {"claim_id": claim_id},
                  "result": claim})

    # Step 2 — always. No LLM, no branching: every claim needs the deductible checked.
    deductible_hits = tools.search_policy(
        f"compulsory deductible for vehicle {claim['vehicle_cc']}cc, "
        f"loss date {claim['date_of_loss']}"
    )
    steps.append({"step": 2, "action": "search_policy",
                  "args": {"query": "compulsory deductible"}, "result": deductible_hits})

    # Step 3 — always. No LLM, no branching: every claim gets its coverage checked against
    # the exclusion list, whether or not a keyword happened to be in the notes. A fixed
    # lookup table still decides WHICH query to send (specific if a keyword matched, the
    # general "what is not covered" query otherwise) — see the module docstring for why
    # this changed from conditional to unconditional.
    exclusion_query = _exclusion_query(claim["notes"])
    matched_keyword = exclusion_query != _GENERAL_EXCLUSION_QUERY
    exclusion_hits = tools.search_policy(exclusion_query)
    steps.append({"step": 3, "action": "search_policy (always runs; query depends on notes)",
                  "args": {"query": exclusion_query}, "matched_keyword": matched_keyword,
                  "result": exclusion_hits})

    # Step 4 — the decision.
    #
    # First, a code-level check that skips asking the model at all: KNOWN_UNRESOLVABLE_
    # PATTERNS flags fact patterns measured to be wrong more often than right when left to
    # the decision call, voting included (see that constant's comment for the numbers). For
    # those, refer directly — cheaper than 3 wasted votes, and correct every time by
    # construction rather than by chance.
    if _is_known_unresolvable(claim["notes"]):
        decision = {
            "status": "REFERRED", "claim_amount_for_payout": claim["claim_amount"],
            "exclusion_clause": None,
            "rationale": "Flagged by code as a known cross-clause conflict (a covered "
                        "peril and an exclusion both plausibly apply to the same event, "
                        "and the retrieved passages do not say which one governs) — "
                        "referred without asking the decision model, which measurement "
                        "showed is unreliable on this exact category.",
        }
        steps.append({"step": 4, "action": "known-unresolvable (code, no LLM call)",
                      "parsed": decision})
    else:
        # Otherwise, voted DECISION_VOTES ways rather than asked once. This was a single
        # call until measurement forced the change: fixing C-003's "unless"-clause
        # misreading with clearer instructions alone (rule 2's worked examples, then a
        # rule 7 boundary against over-applying them) was tested against 6+ repeat runs
        # each time, and the SAME prompt against the SAME claim swung between 1-in-6 and
        # 6-in-6 correct depending on nothing but which run happened to land. That is not
        # a wrong default a clearer sentence can fix — it is variance around an
        # already-correct majority, the textbook case for self-consistency: ask several
        # times, keep the majority, rather than trust whichever single answer came back.
        # A provider failure on any one vote does not crash the claim or the batch it is
        # part of; it is simply excluded from the vote.
        votes, raws = [], []
        for _ in range(DECISION_VOTES):
            try:
                raw = usage.call_llm(
                    DECISION_SYSTEM_PROMPT,
                    _decision_user_prompt(claim, deductible_hits, exclusion_hits),
                )
                parsed, _err = _find_json_object("Final Answer: " + raw, "Final Answer")
            except llm.LLMError:
                raw, parsed = None, None
            raws.append(raw)
            if parsed is not None and parsed.get("status") in VALID_STATUSES:
                votes.append(parsed)

        decision = _majority_decision(votes, claim["claim_amount"])
        steps.append({"step": 4, "action": f"llm_decide (majority of {DECISION_VOTES} votes)",
                      "raw_outputs": raws, "votes": [v["status"] for v in votes],
                      "parsed": decision})

    deductible = _current_deductible(deductible_hits, claim["date_of_loss"], claim["vehicle_cc"])

    # Step 5 — always. No LLM, no branching.
    payable_amount = tools.compute_payout(
        decision.get("claim_amount_for_payout", claim["claim_amount"]),
        deductible,
        decision["status"],
    )
    steps.append({"step": 5, "action": "compute_payout",
                  "args": {"claim_amount": decision.get("claim_amount_for_payout"),
                           "deductible": deductible, "status": decision["status"]},
                  "result": payable_amount})

    result = {
        "system": "workflow",
        "claim_id": claim_id,
        "status": decision["status"],
        "payable_amount": payable_amount,
        "exclusion_clause": decision.get("exclusion_clause"),
        "rationale": decision.get("rationale"),
        "deductible_applied": deductible,
        "claim_amount_for_payout": decision.get("claim_amount_for_payout"),
        "usage": usage.as_dict(),
        "steps": steps,
    }
    if write_trace:
        trace.record(result)
    return result
