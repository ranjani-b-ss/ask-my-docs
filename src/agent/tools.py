"""The three tools. Both the agent and the workflow call these exact same functions —
that is what makes the Week 7 race a fair comparison rather than two different apps.

Each tool has ONE job and its description says so explicitly, in the negative as well as the
positive ("does not X"). That negative half is what requirement 1 is really testing: three
tools whose descriptions never overlap enough for a model to reach for the wrong one. The
common failure this guards against is "get_claim and search_policy both sound like they
fetch information" — spelling out what each one does NOT do is what a one-line summary
usually skips, and it is exactly where two similar tools start to blur into each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import claims_store
from ..config import CANDIDATE_K, DEFAULT_CHUNKING, TOP_K
from ..retriever import retrieve

CORPUS_ID = "insurance"


class ClaimStatus(str, Enum):
    """The only three coverage decisions either system is allowed to reach.

    A plain string parameter lets a model send ``"payable"``, ``"Payable"``, or
    ``"approved"`` and have the tool guess what was meant. An enum makes the three legal
    values part of the tool's declared contract, so a value outside it is a caller error to
    catch, not a string to interpret.
    """

    PAYABLE = "PAYABLE"
    NOT_PAYABLE = "NOT_PAYABLE"
    REFERRED = "REFERRED"


# --------------------------------------------------------------------------------- tool 1


TOOL_GET_CLAIM = {
    "name": "get_claim",
    "description": (
        "Fetch the claim file for one claim by its claim_id: the date of loss, the "
        "vehicle's engine size, the amount claimed, and the adjuster's notes on how the "
        "loss happened. Call this FIRST, always — it is the only source of the facts of "
        "the claim. It does not search the policy wording and it does not compute any "
        "amount; for those, use search_policy and compute_payout."
    ),
    "parameters": {"claim_id": "string, e.g. 'C-004'"},
}


def get_claim(claim_id: str) -> dict:
    claim = claims_store.get(claim_id)
    return {
        "claim_id": claim.claim_id,
        "date_of_loss": claim.date_of_loss,
        "vehicle_cc": claim.vehicle_cc,
        "claim_amount": claim.claim_amount,
        "notes": claim.notes,
    }


# --------------------------------------------------------------------------------- tool 2


TOOL_SEARCH_POLICY = {
    "name": "search_policy",
    "description": (
        "Search the motor own-damage policy wording and its endorsements with a free-text "
        "query, and return the matching clause text with its document id and effective "
        "date. Use this to check whether something in the adjuster's notes triggers an "
        "exclusion (a fact pattern, not a claim_id), or to find which figure — such as the "
        "compulsory deductible — is currently in force for a given date of loss, since an "
        "endorsement can supersede the base wording. It does not fetch a specific claim's "
        "facts and it does not compute any amount."
    ),
    "parameters": {"query": "string — what you are trying to find in the policy wording"},
}


def search_policy(query: str, top_k: int = 3) -> list[dict]:
    result = retrieve(query, cfg=DEFAULT_CHUNKING, corpus_id=CORPUS_ID, top_k=top_k,
                      candidate_k=CANDIDATE_K, min_cosine=0.0, min_rerank_score=0.0)
    return [
        {
            "document_id": hit.meta.get("document_id"),
            "effective_date": hit.meta.get("effective_date"),
            "section": hit.meta.get("section"),
            "text": hit.text,
            "relevance": hit.rerank_score if hit.rerank_score is not None else hit.cosine,
        }
        for hit in result.hits
    ]


# --------------------------------------------------------------------------------- tool 3
# Added for Week 7 Task Set D, requirement 1. See WEEK7.md for the before/after description
# diff against the two tools above.


TOOL_COMPUTE_PAYOUT = {
    "name": "compute_payout",
    "description": (
        "Compute the exact amount payable to the claimant, given the claim amount to pay "
        "against, the compulsory deductible that applies, and the coverage decision "
        "(status). Use this ONLY after you have already decided PAYABLE, NOT_PAYABLE, or "
        "REFERRED from the claim facts and the policy wording — this tool does not decide "
        "coverage, does not read claim files, and does not search policy documents; it "
        "only performs the arithmetic once every input to that arithmetic is already known."
    ),
    "parameters": {
        "claim_amount": "number — the amount to pay against, after excluding any line item "
                        "the policy does not cover (e.g. hire-car charges)",
        "deductible": "number — the compulsory deductible currently in force for this claim",
        "status": "enum: PAYABLE | NOT_PAYABLE | REFERRED",
    },
}


def compute_payout(claim_amount: float, deductible: float, status: str) -> float | None:
    try:
        decision = ClaimStatus(status.strip().upper())
    except ValueError:
        raise ValueError(
            f"status must be one of {[s.value for s in ClaimStatus]}, got {status!r}"
        ) from None

    if decision is ClaimStatus.NOT_PAYABLE:
        return 0.0
    if decision is ClaimStatus.REFERRED:
        return None
    return max(0.0, round(float(claim_amount) - float(deductible), 2))


TOOLS = {
    "get_claim": (TOOL_GET_CLAIM, get_claim),
    "search_policy": (TOOL_SEARCH_POLICY, search_policy),
    "compute_payout": (TOOL_COMPUTE_PAYOUT, compute_payout),
}


def warm_up() -> float:
    """Force the embedder and reranker ONNX sessions to load, and return how long that took.

    Both are lazy singletons (``get_embedder`` / ``get_reranker`` in ``retriever.py``), so the
    first real ``search_policy`` call in a fresh process pays their load cost — measured at
    roughly 100-200 seconds cold on this machine, entirely model-loading, nothing to do with
    the claim being triaged. Folding that into claim 1's latency would make it look 100x
    slower than every other claim for a reason that has nothing to do with the system being
    measured. The race harness calls this once, before timing anything, and reports it
    separately.
    """
    import time

    start = time.perf_counter()
    search_policy("warm up", top_k=1)
    return time.perf_counter() - start


def dispatch(tool_name: str, args: dict):
    """Call a tool by name with keyword args parsed from the model's Action Input."""
    if tool_name not in TOOLS:
        raise KeyError(f"Unknown tool {tool_name!r}. Available: {sorted(TOOLS)}")
    _, fn = TOOLS[tool_name]
    return fn(**args)
