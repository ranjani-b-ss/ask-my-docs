#!/usr/bin/env python
"""Week 9 — server two: the claims platform team's server, standing between the agent and
claim status / adjuster note history. Framed in this exercise as a third-party server the
platform team stood up (see risk_note.md) — in practice, since there is no real separate
team in this training project, it is built here too, but kept deliberately independent of
anything server one or the agent module import, so adding it is provably a config change.

    ./.venv/bin/python src/mcp_servers/claims_system_server.py

Runs over stdio. No LLM here either — see src/agent/mcp_client.py for where the model runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastmcp import FastMCP

from src.agent import claims_store

mcp = FastMCP(name="claims-system")


def _not_found_error(claim_number: str) -> ValueError:
    # Requirement 5's whole point: "Error 3" and this message return through the exact same
    # code path, to the exact same model, asking the exact same question — the only thing
    # that changed is whether the text tells the model what to do next. See
    # error_before_after.md for what each one actually cost in laps, tokens and an answer
    # the user could act on.
    valid = ", ".join(claims_store.all_claim_ids())
    return ValueError(
        f"claim {claim_number!r} not found: claim numbers in this system look like "
        f"C-NNN (a letter C, a hyphen, three digits — for example C-001). Known claim "
        f"numbers right now: {valid}. If the number you were given matches this format "
        f"and still isn't found, the claim may not exist in this system at all — say so "
        f"rather than retrying the identical call."
    )


@mcp.tool
def get_claim_status(claim_number: str) -> dict:
    """Look up the status of one motor own-damage claim by its claim number.

    Claim numbers in this system look like C-NNN (a letter C, a hyphen, three digits — for
    example C-001), NOT the CLM-YYYY-NNNNN format some other insurance systems use. Returns
    the date of loss, the vehicle's engine size, and the amount claimed. Does not return the
    adjuster's notes — call get_adjuster_notes for those. Raises a clear error naming the
    expected format if the claim number doesn't exist; that error is not a reason to retry
    the identical call.
    """
    try:
        claim = claims_store.get(claim_number)
    except KeyError:
        raise _not_found_error(claim_number)
    return {
        "claim_id": claim.claim_id,
        "date_of_loss": claim.date_of_loss,
        "vehicle_cc": claim.vehicle_cc,
        "claim_amount": claim.claim_amount,
    }


@mcp.tool
def get_adjuster_notes(claim_number: str) -> dict:
    """Get the adjuster's free-text narrative for one motor own-damage claim by its claim
    number, describing how the loss happened.

    Claim numbers in this system look like C-NNN (a letter C, a hyphen, three digits — for
    example C-001), NOT the CLM-YYYY-NNNNN format some other insurance systems use. Does not
    return the claim's status, date of loss, or amount — call get_claim_status for those.
    Raises a clear error naming the expected format if the claim number doesn't exist; that
    error is not a reason to retry the identical call.
    """
    try:
        claim = claims_store.get(claim_number)
    except KeyError:
        raise _not_found_error(claim_number)
    return {"claim_id": claim.claim_id, "notes": claim.notes}


if __name__ == "__main__":
    mcp.run()
