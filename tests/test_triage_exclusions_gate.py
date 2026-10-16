"""Week 12 — a claim may not be referred until the policy's exclusion clause has been READ (host-enforced, no model, no index).

The agent builds its own search queries from the claim's vocabulary, and an exclusion rarely uses it, so whether the exclusion
list ever reached the model was query luck. The gate removes the luck; it names no policy wording (the section TITLE only).
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from src import claim_files, llm
from src.agent import triage_agent as ta
from src.agent.budgets import Budgets

CLAIM = "CLM-2026-00601"
BUDGET = Budgets(max_iterations=14, max_tokens=30_000, max_cost_usd=1, max_wall_seconds=60)
USAGE = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20, "cost_usd": 0.0}

OTHER_HIT = {"chunk_id": "PW-MOTOR-001::3", "document_id": "PW-MOTOR-001", "version": "5.1", "effective_date": "2025-04-01",
             "clause": "Policy > 2.2 Compulsory deductible", "text": "deductible", "superseded_by": None}
EXCL_HIT = {"chunk_id": "PW-MOTOR-001::4", "document_id": "PW-MOTOR-001", "version": "5.1", "effective_date": "2025-04-01",
            "clause": "Policy > 3. What is not covered", "text": "the list", "superseded_by": None}
FINAL = ('Thought: done.\nFinal Answer: {"facts": [], "exclusion_candidates": [], "wording_relevant": [], '
         '"referral_reason": "Adjuster to review.", "summary_for_adjuster": "Adjuster to review."}')


def act(tool, args):
    return f"Thought: next.\nAction: {tool}\nAction Input: {json.dumps(args)}"


class Registry:
    def __init__(self, searches):
        schema = {"properties": {"trace_id": {"type": "string"}}}
        self.tools = {n: SimpleNamespace(name=n, description="d", input_schema=schema, server="s")
                      for n in ("lookup_policy", "check_in_force", "search_wording", "get_limits", "refer_to_adjuster")}
        self._searches = iter(searches)
        self.calls = []

    async def dispatch(self, tool, args):
        self.calls.append(tool)
        if tool == "lookup_policy":
            return json.dumps({"claim_number": CLAIM, "policy_number": "MOT-1", "product": "motor", "loss_date": "2026-03-31"})
        if tool == "check_in_force":
            return json.dumps({"in_force": True, "reason": "inside the window"})
        if tool == "search_wording":
            return json.dumps({"hits": next(self._searches), "index": "structured_800_150"})
        if tool == "get_limits":
            return json.dumps({"deductible": {"applies": True, "amount": 1000}, "sub_limits": [], "policy_limit": {"amount": 1}})
        return json.dumps({"referral_id": "REF-T", "queue": "adjuster", "claim_number": CLAIM, "recorded": True})


def run(monkeypatch, script, searches):
    replies = iter(script)
    seen = []

    def fake(system, user, **kw):
        seen.append(user)
        return next(replies), USAGE
    monkeypatch.setattr(llm, "chat_with_usage", fake)
    reg = Registry(searches)
    result = asyncio.run(ta.run_with_registry(reg, CLAIM, budgets=BUDGET, write_trace=False))
    return result, reg, seen


BASE = [act("lookup_policy", {"claim_number": CLAIM}), act("check_in_force", {"policy_number": "x", "loss_date": "y"}),
        act("search_wording", {"query": "deductible", "product": "motor", "loss_date": "2026-03-31"}),
        act("get_limits", {"claim_number": CLAIM})]


def test_referral_is_blocked_until_the_exclusion_clause_has_been_retrieved(monkeypatch):
    monkeypatch.delenv("TRIAGE_EXCLUSIONS_GATE", raising=False)
    script = BASE + [act("refer_to_adjuster", {"claim_number": CLAIM, "reason": "r"}),
                     act("search_wording", {"query": "What is not covered", "product": "motor", "loss_date": "x"}),
                     act("refer_to_adjuster", {"claim_number": CLAIM, "reason": "r"}), FINAL]
    result, reg, seen = run(monkeypatch, script, [[OTHER_HIT], [EXCL_HIT]])
    assert result["stop_reason"] == "final_answer"
    assert [b["tool"] for b in result["blocked"]] == ["refer_to_adjuster"]
    assert 'What is not covered' in result["blocked"][0]["reason"]
    assert reg.calls.count("refer_to_adjuster") == 1                   # blocked once, executed once
    assert result["index"] == "structured_800_150"                      # the host records which index the server used


def test_the_block_message_names_the_section_title_and_no_policy_wording(monkeypatch):
    monkeypatch.delenv("TRIAGE_EXCLUSIONS_GATE", raising=False)
    script = BASE + [act("refer_to_adjuster", {"claim_number": CLAIM, "reason": "r"}),
                     act("search_wording", {"query": "What is not covered", "product": "motor", "loss_date": "x"}),
                     act("refer_to_adjuster", {"claim_number": CLAIM, "reason": "r"}), FINAL]
    result, _, _ = run(monkeypatch, script, [[OTHER_HIT], [EXCL_HIT]])
    msg = result["blocked"][0]["reason"].lower()
    assert "geographical" not in msg and "licence" not in msg and "hire" not in msg and "nepal" not in msg


def test_when_the_first_search_already_returned_the_clause_nothing_is_blocked(monkeypatch):
    monkeypatch.delenv("TRIAGE_EXCLUSIONS_GATE", raising=False)
    script = BASE + [act("refer_to_adjuster", {"claim_number": CLAIM, "reason": "r"}), FINAL]
    result, _, _ = run(monkeypatch, script, [[OTHER_HIT, EXCL_HIT]])
    assert result["blocked"] == [] and result["stop_reason"] == "final_answer"


def test_with_the_gate_off_the_old_behaviour_returns(monkeypatch):
    monkeypatch.setenv("TRIAGE_EXCLUSIONS_GATE", "off")
    script = BASE + [act("refer_to_adjuster", {"claim_number": CLAIM, "reason": "r"}), FINAL]
    result, _, _ = run(monkeypatch, script, [[OTHER_HIT]])
    assert result["blocked"] == [] and result["stop_reason"] == "final_answer"


def test_a_lapsed_policy_is_not_asked_to_read_exclusions():
    s = ta.RunState(trace_id="t", claim=claim_files.get(CLAIM))
    s.called += ["lookup_policy", "check_in_force"]
    s.in_force = False
    assert ta.missing_steps(s) == []


def test_only_a_not_covered_section_counts_as_the_exclusion_clause():
    assert ta.hits_exclusion_clause([EXCL_HIT]) and not ta.hits_exclusion_clause([OTHER_HIT])
    assert not ta.hits_exclusion_clause([]) and not ta.hits_exclusion_clause(None)
    assert ta.hits_exclusion_clause([{"clause": "Group Health > 6. What is not covered"}])
