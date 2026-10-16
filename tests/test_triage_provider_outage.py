"""Week 12 — SEAMS.md S15: a provider outage must not lose the claim.

The invariant is "every request ends in a referral". In the first integrated run the Gemini quota
ran out and 10 runs (9 claims) ended with no referral at all, because the host's backstop only
fired once `lookup_policy` had set the loss date and a dead model never got that far.

No model and no MCP server: the provider is a stub that always fails (or fails after the first
lap), and the registry is a recorder.
"""

import asyncio
import json
from types import SimpleNamespace

from src import llm
from src.agent import triage_agent as ta
from src.agent.budgets import Budgets

CLAIM = "CLM-2026-00601"
SMALL_BUDGET = Budgets(max_iterations=3, max_tokens=30_000, max_cost_usd=0.03, max_wall_seconds=60.0)


class RecordingRegistry:
    """Stands in for MCPToolRegistry: lists the five tools, records every dispatch."""

    def __init__(self):
        schema = {"properties": {"trace_id": {"type": "string"}}}
        self.tools = {name: SimpleNamespace(name=name, description="d", input_schema=schema,
                                            server="claims-system")
                      for name in ("lookup_policy", "check_in_force", "search_wording",
                                   "get_limits", "refer_to_adjuster")}
        self.calls: list[tuple[str, dict]] = []

    async def dispatch(self, tool: str, args: dict) -> str:
        self.calls.append((tool, args))
        if tool == "lookup_policy":
            return json.dumps({"claim_number": CLAIM, "policy_number": "MOT-2025-0021",
                               "product": "motor", "loss_date": "2026-03-31"})
        if tool == "refer_to_adjuster":
            return json.dumps({"referral_id": "REF-TEST0001", "queue": "adjuster",
                               "claim_number": args["claim_number"], "recorded": True})
        return json.dumps({})

    def referrals(self) -> list[dict]:
        return [a for t, a in self.calls if t == "refer_to_adjuster"]


def _run(registry):
    return asyncio.run(ta.run_with_registry(registry, CLAIM, budgets=SMALL_BUDGET, write_trace=False))


def _provider_always_down(monkeypatch):
    def boom(*args, **kwargs):
        raise llm.LLMError("Gemini quota exceeded (429) twice.")
    monkeypatch.setattr(llm, "chat_with_usage", boom)


def test_a_provider_that_is_down_from_the_first_call_still_yields_one_referral(monkeypatch):
    _provider_always_down(monkeypatch)
    reg = RecordingRegistry()
    result = _run(reg)
    refs = reg.referrals()
    assert len(refs) == 1, f"expected exactly one referral, got {len(refs)}"
    assert refs[0]["claim_number"] == CLAIM
    assert refs[0]["flags"] == ["triage_incomplete"]
    assert result["packet"]["referral"]["referral_id"] == "REF-TEST0001"
    assert result["packet"]["decision"] is None
    assert [t for t, _ in reg.calls] == ["refer_to_adjuster"]       # nothing else was attempted


def test_the_forced_referral_reason_says_why_triage_did_not_complete(monkeypatch):
    _provider_always_down(monkeypatch)
    reg = RecordingRegistry()
    _run(reg)
    assert "did not complete" in reg.referrals()[0]["reason"]


def test_a_provider_that_dies_after_lookup_still_yields_exactly_one_referral(monkeypatch):
    replies = iter(['Thought: start.\nAction: lookup_policy\nAction Input: {"claim_number": "%s"}' % CLAIM])
    usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20, "cost_usd": 0.0}

    def flaky(*args, **kwargs):
        try:
            return next(replies), usage
        except StopIteration:
            raise llm.LLMError("Gemini quota exceeded (429) twice.")
    monkeypatch.setattr(llm, "chat_with_usage", flaky)
    reg = RecordingRegistry()
    _run(reg)
    assert [t for t, _ in reg.calls] == ["lookup_policy", "refer_to_adjuster"]
    assert len(reg.referrals()) == 1
