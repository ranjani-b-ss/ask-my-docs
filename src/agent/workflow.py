"""The same triage task, done as a fixed sequence — no loop, no LLM deciding what to do next.

Four steps, always in this order, always all four:

    1. get_claim            — code, no LLM
    2. search_policy         — code, no LLM (the deductible clause, always)
    3. search_policy         — code, no LLM (an exclusion clause, ONLY if a fixed keyword
                                map matches something in the notes)
    4. one LLM call          — decide status + the amount to pay against, from what steps
                                1-3 already fetched
    5. compute_payout        — code, no LLM

Step 3's branching is the point of comparison with the agent: the agent decides whether to
search for an exclusion by *reading and reasoning about* the notes; this workflow decides
the identical question with a fixed keyword table. Same tools, same model for step 4, same
output contract as ``react_agent.run`` — the only thing this file does not contain is a loop.
"""

from __future__ import annotations

import re

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


def _exclusion_query(notes: str) -> str | None:
    """First matching canned query, or None if nothing in the notes trips a keyword.

    Fixed code, deterministic, no model involved — the workflow's answer to the same
    "does step 3 depend on what step 2 found" dependency the agent handles by reasoning.
    """
    for pattern, query in EXCLUSION_KEYWORDS.items():
        if re.search(pattern, notes, re.IGNORECASE):
            return query
    return None


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
the facts do not satisfy.
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
6. If the passages genuinely do not settle whether the loss is covered, output REFERRED.
"""


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
        parts.append(f"POLICY PASSAGES — POSSIBLE EXCLUSION\n{fmt(exclusion_hits)}")
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

    # Step 3 — a fixed lookup table decides whether this runs, not the model.
    exclusion_query = _exclusion_query(claim["notes"])
    exclusion_hits = None
    if exclusion_query:
        exclusion_hits = tools.search_policy(exclusion_query)
    steps.append({"step": 3, "action": "search_policy (conditional, keyword-triggered)",
                  "args": {"query": exclusion_query}, "triggered": exclusion_query is not None,
                  "result": exclusion_hits})

    # Step 4 — the one LLM call in this whole pipeline. A provider failure here is not
    # allowed to crash the claim (or the batch it is part of) any more than a malformed
    # response is — both fail safe to REFERRED, same as the agent's budget-exceeded path.
    try:
        raw = usage.call_llm(DECISION_SYSTEM_PROMPT,
                             _decision_user_prompt(claim, deductible_hits, exclusion_hits))
        decision, err = _find_json_object("Final Answer: " + raw, "Final Answer")
    except llm.LLMError as exc:
        raw, decision, err = None, None, str(exc)

    if decision is None or decision.get("status") not in VALID_STATUSES:
        decision = {"status": "REFERRED", "claim_amount_for_payout": claim["claim_amount"],
                    "exclusion_clause": None,
                    "rationale": f"Decision step did not return a usable answer: {err}"}
    steps.append({"step": 4, "action": "llm_decide", "raw_output": raw, "parsed": decision})

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
