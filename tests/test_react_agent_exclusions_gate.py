"""Week 11 follow-up — a decision is rejected until the policy's exclusion clause has been retrieved.

Drives the REAL `react_agent.run` loop with a scripted model and stubbed tools: no LLM, no index. The point of the gate is
that the agent used to answer without ever having seen the exclusion list (C-011), because nothing required that it had.
"""

import json

import pytest

from src.agent import react_agent as ra
from src.agent import tools
from src.agent.budgets import Budgets
from src.agent.usage import UsageAccumulator

ANSWER = ('Thought: done.\nFinal Answer: {"status": "NOT_PAYABLE", "payable_amount": 0.0, '
          '"exclusion_clause": "PW-MOTOR-001 3", "rationale": "excluded"}')
SCRIPT = [
    'Thought: claim.\nAction: get_claim\nAction Input: {"claim_id": "C-011"}',
    'Thought: search.\nAction: search_policy\nAction Input: {"query": "deductible"}',
    'Thought: pay.\nAction: compute_payout\nAction Input: {"claim_amount": 28000, "deductible": 1500, "status": "NOT_PAYABLE"}',
    ANSWER,
    'Thought: read exclusions.\nAction: search_policy\nAction Input: {"query": "what is not covered"}',
    ANSWER,
]
OTHER = [{"chunk_id": "PW-MOTOR-001::3", "section": "Policy > 2.2 Compulsory deductible", "text": "deductible INR 1,500"}]
EXCL = [{"chunk_id": "PW-MOTOR-001::4", "section": "Policy > 3. What is not covered", "text": "- outside the geographical area"}]


@pytest.fixture
def run_script(monkeypatch):
    def go(search_results):
        replies = iter(SCRIPT)
        searches = iter(search_results)
        go.seen = []                                              # every user turn the model was sent

        def scripted(self, system, user):
            go.seen.append(user)
            return next(replies)
        monkeypatch.setattr(UsageAccumulator, "call_llm", scripted)

        def fake_dispatch(name, args):
            if name == "get_claim":
                return {"claim_id": "C-011", "notes": "x"}
            if name == "search_policy":
                return next(searches)
            return 0.0                                          # compute_payout
        monkeypatch.setattr(tools, "dispatch", fake_dispatch)
        return ra.run("C-011", budgets=Budgets(max_iterations=12, max_tokens=30_000, max_cost_usd=1, max_wall_seconds=60),
                      write_trace=False)
    return go


def test_a_decision_is_rejected_until_the_exclusion_clause_was_retrieved(run_script, monkeypatch):
    monkeypatch.delenv("AGENT_EXCLUSIONS_GATE", raising=False)
    result = run_script([OTHER, EXCL])
    assert result["status"] == "NOT_PAYABLE" and result["stop_reason"] == "final_answer"
    finals = [s for s in result["steps"] if (s.get("parsed") or {}).get("kind") == "final"]
    assert [f["payout_verified"] for f in finals] == [False, True]          # first rejected, second accepted
    assert [f["exclusions_read"] for f in finals] == [False, True]


def test_the_rejection_names_no_policy_wording(run_script, monkeypatch):
    monkeypatch.delenv("AGENT_EXCLUSIONS_GATE", raising=False)
    run_script([OTHER, EXCL])
    sent_after_rejection = run_script.seen[4]                 # the turn after the first, rejected, Final Answer
    assert "REJECTED — no search_policy result this run has returned the policy's exclusion clause" in sent_after_rejection
    rejection = sent_after_rejection.split("Observation: REJECTED")[1].split("\n\n")[0].lower()
    assert "geographical" not in rejection and "nepal" not in rejection and "hire" not in rejection
    assert "geographical" not in ra.SYSTEM_PROMPT.lower() and "nepal" not in ra.SYSTEM_PROMPT.lower()


def test_with_the_gate_off_the_first_answer_is_accepted(run_script, monkeypatch):
    monkeypatch.setenv("AGENT_EXCLUSIONS_GATE", "off")
    result = run_script([OTHER, EXCL])
    finals = [s for s in result["steps"] if (s.get("parsed") or {}).get("kind") == "final"]
    assert finals[0]["payout_verified"] is True and result["iterations"] == 4


def test_only_a_not_covered_section_counts():
    assert ra.hits_exclusion_clause(EXCL) and not ra.hits_exclusion_clause(OTHER)
    assert not ra.hits_exclusion_clause([]) and not ra.hits_exclusion_clause(None)
