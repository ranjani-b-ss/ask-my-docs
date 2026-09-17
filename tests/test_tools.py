"""src/agent/tools.py — compute_payout and dispatch. Pure functions, no retrieval, no LLM:
the cheapest, highest-value place to catch an arithmetic or status-handling regression before
it reaches a live claim.
"""

from __future__ import annotations

import pytest

from src.agent import tools


def test_compute_payout_not_payable_is_always_zero():
    assert tools.compute_payout(claim_amount=50000.0, deductible=1000.0, status="NOT_PAYABLE") == 0.0


def test_compute_payout_referred_is_none():
    assert tools.compute_payout(claim_amount=50000.0, deductible=1000.0, status="REFERRED") is None


def test_compute_payout_payable_subtracts_deductible():
    assert tools.compute_payout(claim_amount=8000.0, deductible=1000.0, status="PAYABLE") == 7000.0


def test_compute_payout_never_goes_negative():
    """A deductible larger than the claim amount must floor at 0, not go negative — the model
    could plausibly hand this tool a deductible it misread as larger than the claim."""
    assert tools.compute_payout(claim_amount=500.0, deductible=1000.0, status="PAYABLE") == 0.0


def test_compute_payout_rounds_to_two_decimals():
    assert tools.compute_payout(claim_amount=100.567, deductible=0.0, status="PAYABLE") == 100.57


def test_compute_payout_status_is_case_insensitive():
    assert tools.compute_payout(claim_amount=8000.0, deductible=1000.0, status="payable") == 7000.0
    assert tools.compute_payout(claim_amount=8000.0, deductible=1000.0, status=" Payable ") == 7000.0


def test_compute_payout_rejects_invalid_status():
    with pytest.raises(ValueError, match="must be one of"):
        tools.compute_payout(claim_amount=8000.0, deductible=1000.0, status="approved")


def test_dispatch_unknown_tool_raises_keyerror():
    with pytest.raises(KeyError):
        tools.dispatch("delete_everything", {})


def test_dispatch_routes_to_the_right_function():
    result = tools.dispatch(
        "compute_payout",
        {"claim_amount": 8000.0, "deductible": 1000.0, "status": "PAYABLE"},
    )
    assert result == 7000.0


def test_get_claim_returns_known_claim():
    claim = tools.get_claim("C-001")
    assert claim["claim_id"] == "C-001"
    assert "notes" in claim and claim["notes"]


def test_get_claim_unknown_id_raises():
    with pytest.raises(KeyError):
        tools.get_claim("C-999")


def test_tools_registry_has_exactly_three_tools():
    """Requirement 1 of the Week 7 brief: three tools, one job each. A fourth tool appearing
    here unnoticed would silently widen what the agent can do."""
    assert set(tools.TOOLS) == {"get_claim", "search_policy", "compute_payout"}
