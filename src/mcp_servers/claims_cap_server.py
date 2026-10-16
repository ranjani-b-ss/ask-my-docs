#!/usr/bin/env python
"""Week 12 — the claims-system MCP server the triage agent CONSUMES.

    ./.venv/bin/python src/mcp_servers/claims_cap_server.py

Tools: ``lookup_policy`` (claim -> policy), ``check_in_force`` (was the policy live on the loss
date), ``get_limits`` (deductible / sub-limits / policy limit, resolved to the wording in force
on the loss date) and ``refer_to_adjuster`` (the terminal action — the only way this system ever
"decides" anything is by handing the file to a person).

Authoritative data lives HERE, not in the model's head: the loss date comes from the claims
system, and ``get_limits`` takes only a claim number, so a mistyped date or engine size cannot
produce a wrong number. Nothing returned contains a claimant's name, address or injuries; the
registry holds none and the referral reason is redacted before it is stored.

No LLM runs here.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastmcp import FastMCP

from src import claim_files, limits, redact, registry, span_log

mcp = FastMCP(name="claims-system")
REFERRALS_FILE = span_log.ROOT / "traces" / "referrals.jsonl"


def _no_such_claim(claim_number: str) -> ValueError:
    return ValueError(
        f"no claim {claim_number!r} in the claims system. Claim numbers look like C-001 or "
        f"CLM-2026-00418 — copy the claim number exactly as it was given to you. If it was "
        f"copied correctly and is still not found, the claim does not exist here: refer to an "
        f"adjuster and say so rather than retrying the same number."
    )


def _claim(claim_number: str) -> claim_files.ClaimFile:
    try:
        return claim_files.get(claim_number)
    except KeyError:
        raise _no_such_claim(claim_number) from None


@mcp.tool
def lookup_policy(claim_number: str, trace_id: str = "") -> dict:
    """Find the policy a claim was made under, and the claim's date of loss.

    Call this FIRST. Returns the policy number, the product (`motor` or `health`), the
    authoritative `loss_date` (YYYY-MM-DD) — use that date for every later call, not a date
    from the narrative — and the engine size or insured age where the product needs it.
    Does not say whether the policy was in force on that date (call `check_in_force`) and does
    not return any wording or limits.
    """
    def _do() -> dict:
        cf = _claim(claim_number)
        pol = registry.policy_for_claim(claim_number)
        if pol is None:
            raise ValueError(f"claim {claim_number!r} exists but has no policy on record: refer to an adjuster.")
        out = {"claim_number": cf.claim_number, "policy_number": pol["policy_number"],
               "product": cf.product, "loss_date": cf.loss_date,
               "geographical_area": pol["geographical_area"]}
        if cf.vehicle_cc is not None:
            out["vehicle_cc"] = cf.vehicle_cc
        if cf.insured_age is not None:
            out["insured_age"] = cf.insured_age
        return out

    return span_log.run_logged("claims-system", "lookup_policy", trace_id,
                               {"claim_number": claim_number}, _do,
                               lambda r: {"policy_number": r["policy_number"],
                                          "product": r["product"], "loss_date": r["loss_date"]})


@mcp.tool
def check_in_force(policy_number: str, loss_date: str, trace_id: str = "") -> dict:
    """Check whether a policy was in force on the date of loss.

    Pass the `policy_number` and `loss_date` returned by `lookup_policy`. Returns
    `in_force` (true/false), the in-force window, and a plain-language `reason`. If
    `in_force` is false, no policy wording can be relied on for this loss: do not search the
    wording or fetch limits — go straight to `refer_to_adjuster` and quote the `reason`.
    """
    return span_log.run_logged(
        "claims-system", "check_in_force", trace_id,
        {"policy_number": policy_number, "loss_date": loss_date},
        lambda: registry.check_in_force(policy_number, loss_date),
        lambda r: {"in_force": r["in_force"], "reason": r["reason"]},
    )


@mcp.tool
def get_limits(claim_number: str, trace_id: str = "") -> dict:
    """Get the deductible (or co-payment), the sub-limits and the policy limit for a claim.

    Takes only the claim number: the loss date, engine size, insured age and policy are read
    from the claims system, so the figures are resolved to the wording in force on THIS loss.
    The three numbers are different things and are returned separately — `deductible` (what
    the insured bears first, in INR), `sub_limits` (caps on one kind of loss, such as 50% of
    tyre cost or a per-day room-rent cap) and `policy_limit` (the IDV or sum insured). Report
    them as three numbers; never merge them. Each carries its document, version, clause and the
    loss date it was resolved against. Only call this after `check_in_force` returned true.
    """
    def _do() -> dict:
        cf = _claim(claim_number)
        pol = registry.policy_for_claim(claim_number)
        return limits.get_limits(cf.product, cf.loss_date, cf.vehicle_cc, cf.insured_age, pol)

    def _summary(r: dict) -> dict:
        d = r.get("deductible") or {}
        return {"deductible": d.get("amount"), "deductible_doc": d.get("document_id"),
                "co_payment": (r.get("co_payment") or {}).get("percent"),
                "sub_limits": [s["name"] for s in r.get("sub_limits", [])],
                "policy_limit": (r.get("policy_limit") or {}).get("amount")}

    return span_log.run_logged("claims-system", "get_limits", trace_id,
                               {"claim_number": claim_number}, _do, _summary)


@mcp.tool
def refer_to_adjuster(claim_number: str, reason: str, flags: list[str] | None = None,
                      trace_id: str = "") -> dict:
    """Hand the claim file to a human adjuster. ALWAYS the last tool call.

    This is the only outcome this system produces: it does not decide, approve or decline
    anything. `reason` is one or two neutral sentences saying what the adjuster should look at
    (for example "the facts make the licence exclusion arguable; policy not in force on the
    loss date"). `flags` is an optional list of short tags such as `exclusion_arguable`,
    `policy_not_in_force`, `limits_resolved`. Do not put any person's name, address or injury
    in the reason — describe the facts without identifying anyone.
    """
    def _do() -> dict:
        _claim(claim_number)
        record = {"referral_id": f"REF-{uuid.uuid4().hex[:8].upper()}", "claim_number": claim_number,
                  "queue": "adjuster", "reason": redact.scrub_claimant(reason),
                  "flags": list(flags or []), "trace_id": trace_id or None,
                  "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        REFERRALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with REFERRALS_FILE.open("a", encoding="utf-8") as fh:
            import json
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"referral_id": record["referral_id"], "queue": "adjuster",
                "claim_number": claim_number, "recorded": True}

    return span_log.run_logged("claims-system", "refer_to_adjuster", trace_id,
                               {"claim_number": claim_number, "reason": reason, "flags": flags},
                               _do, lambda r: {"referral_id": r["referral_id"]})


if __name__ == "__main__":
    mcp.run()
