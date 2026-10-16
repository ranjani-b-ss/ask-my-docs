"""Week 12 — the code-enforced rules of the triage agent, with no model and no MCP server.

Each test is one sentence of the brief turned into an assertion: the date is enforced by code,
tool order is enforced, the model can only cite what was retrieved, the version on a citation
comes from the retrieved chunk and not from the model, and every run ends in a referral.
"""

from src import claim_files
from src.agent import triage_agent as ta


def _state(claim="CLM-2026-00601"):
    s = ta.RunState(trace_id="cap_test", claim=claim_files.get(claim))
    return s


def _looked_up(s, in_force=None):
    s.called.append("lookup_policy")
    s.policy_number, s.loss_date, s.product = "MOT-2025-0001", "2026-03-31", "motor"
    if in_force is not None:
        s.called.append("check_in_force")
        s.in_force = in_force
        s.in_force_result = {"in_force": in_force, "reason": "r"}
    return s


HIT = {"chunk_id": "PW-MOTOR-001::3", "document_id": "PW-MOTOR-001", "version": "5.1",
       "effective_date": "2025-04-01", "clause": "2.2 Compulsory deductible",
       "text": "A compulsory deductible of **INR 1,000** applies ...", "relevance": 0.9}


# ---------------------------------------------------------------- the date is enforced, not asked for

def test_model_supplied_loss_date_is_overwritten_and_recorded():
    s = _looked_up(_state(), in_force=True)
    args, overrides = ta.authoritative_args(
        s, "search_wording", {"query": "deductible", "loss_date": "2026-12-31", "product": "health"})
    assert args["loss_date"] == "2026-03-31" and args["product"] == "motor"
    assert {(o["arg"], o["model_sent"], o["used"]) for o in overrides} == {
        ("loss_date", "2026-12-31", "2026-03-31"), ("product", "health", "motor")}


def test_matching_arguments_produce_no_override():
    s = _looked_up(_state(), in_force=True)
    _, overrides = ta.authoritative_args(
        s, "search_wording", {"query": "q", "loss_date": "2026-03-31", "product": "motor"})
    assert overrides == []


def test_model_cannot_triage_a_different_claim():
    s = _state("CLM-2026-00601")
    args, overrides = ta.authoritative_args(s, "get_limits", {"claim_number": "C-001"})
    assert args["claim_number"] == "CLM-2026-00601"
    assert overrides and overrides[0]["model_sent"] == "C-001"


# ---------------------------------------------------------------- tool order is enforced

def test_nothing_runs_before_lookup():
    s = _state()
    for tool in ("check_in_force", "search_wording", "get_limits", "refer_to_adjuster"):
        assert ta.gate(s, tool).startswith("BLOCKED"), tool
    assert ta.gate(s, "lookup_policy") is None


def test_wording_is_blocked_when_the_policy_was_not_in_force():
    s = _looked_up(_state(), in_force=False)
    assert "not in force" in ta.gate(s, "search_wording")
    assert "not in force" in ta.gate(s, "get_limits")
    assert ta.gate(s, "refer_to_adjuster") is None        # nothing else is needed — go straight to referral


def test_referral_is_blocked_until_wording_and_limits_are_done():
    s = _looked_up(_state(), in_force=True)
    msg = ta.gate(s, "refer_to_adjuster")
    assert "search_wording" in msg and "get_limits" in msg
    s.searches = 1
    s.called.append("get_limits")
    assert "What is not covered" in ta.gate(s, "refer_to_adjuster")      # a search is not enough: the exclusion clause must be read
    s.exclusions_read = True
    assert ta.gate(s, "refer_to_adjuster") is None


def test_wording_search_requires_the_in_force_check_first():
    s = _looked_up(_state())
    assert "check_in_force" in ta.gate(s, "search_wording")


# ---------------------------------------------------------------- the model may only cite what was retrieved

def _answer(**over):
    base = {"facts": ["f"], "exclusion_candidates": [], "referral_reason": "r",
            "summary_for_adjuster": "s"}
    return {**base, **over}


def _ready(s):
    _looked_up(s, in_force=True)
    s.searches = 1
    s.exclusions_read = True
    s.called.append("get_limits")
    s.referral = {"referral_id": "REF-1", "queue": "adjuster"}
    s.retrieved[HIT["chunk_id"]] = HIT
    return s


def test_an_invented_chunk_id_bounces_the_answer():
    s = _ready(_state())
    reason = ta.validate_final(s, _answer(exclusion_candidates=[{"chunk_id": "END-9999::1", "why": "x"}]))
    assert "END-9999::1" in reason and "PW-MOTOR-001::3" in reason


def test_a_retrieved_chunk_id_is_accepted():
    s = _ready(_state())
    assert ta.validate_final(s, _answer(exclusion_candidates=[{"chunk_id": HIT["chunk_id"], "why": "x"}])) is None


def test_final_answer_before_referral_is_bounced():
    s = _ready(_state())
    s.referral = None
    assert "refer_to_adjuster" in ta.validate_final(s, _answer())


def test_missing_field_is_named():
    s = _ready(_state())
    a = _answer()
    del a["summary_for_adjuster"]
    assert "summary_for_adjuster" in ta.validate_final(s, a)


# ---------------------------------------------------------------- the version on a citation is not the model's to write

def test_citation_version_comes_from_the_retrieved_chunk():
    s = _ready(_state())
    packet = ta.build_packet(
        s, _answer(exclusion_candidates=[{"chunk_id": HIT["chunk_id"], "why": "arguable"}],
                   referral_reason="adjuster to review"), [])
    w = packet["wording"][0]
    assert (w["document_id"], w["version"], w["effective_date"]) == ("PW-MOTOR-001", "5.1", "2025-04-01")
    assert w["resolved_against"] == "2026-03-31"
    assert "v5.1" in w["citation"] and "resolved against loss date 2026-03-31" in w["citation"]


def test_packet_states_no_decision_and_keeps_the_referral():
    s = _ready(_state())
    packet = ta.build_packet(s, _answer(), [])
    assert packet["decision"] is None
    assert packet["referral"]["referral_id"] == "REF-1"
    assert packet["referral"]["reason"] == "r"


# ---------------------------------------------------------------- parsing

def test_parse_action_and_final():
    a = ta._parse_lap('Thought: x\nAction: lookup_policy\nAction Input: {"claim_number": "C-001"}')
    assert a == {"kind": "action", "tool": "lookup_policy", "args": {"claim_number": "C-001"}}
    f = ta._parse_lap('Thought: done\nFinal Answer: {"facts": []}')
    assert f["kind"] == "final" and f["answer"] == {"facts": []}
    assert ta._parse_lap("no structure here")["kind"] == "malformed"


def test_trace_id_is_hidden_from_the_model_but_present_in_the_schema():
    from src.agent.mcp_client import DiscoveredTool
    tool = DiscoveredTool("t", "desc", {"properties": {"claim_number": {"type": "string"},
                                                       "trace_id": {"type": "string"}}}, "s")
    block = ta._tool_block({"t": tool})
    assert "claim_number" in block and "trace_id" not in block


# ---------------------------------------------------------------- S9: model text in tool ARGS is guarded too

def test_referral_reason_that_states_an_outcome_is_replaced_and_recorded():
    s = _state()
    out = ta.guard_tool_args(s, "refer_to_adjuster",
                             {"claim_number": "x", "reason": "This loss is covered.", "flags": ["limits_resolved"]})
    assert "covered" not in out["reason"].lower()
    assert out["flags"] == ["limits_resolved"]
    assert s.arg_violations and s.arg_violations[0]["tool"] == "refer_to_adjuster"


def test_neutral_referral_reason_is_untouched_and_other_tools_are_ignored():
    s = _state()
    args = {"claim_number": "x", "reason": "Facts make the licence exclusion arguable.", "flags": []}
    assert ta.guard_tool_args(s, "refer_to_adjuster", args) == args
    assert ta.guard_tool_args(s, "search_wording", {"query": "is covered"}) == {"query": "is covered"}
    assert s.arg_violations == []


def test_a_second_referral_is_blocked():
    """S19: the gate checked order only, so a model could refer twice and leave two records for one claim."""
    s = _looked_up(_state(), in_force=False)
    assert ta.gate(s, "refer_to_adjuster") is None
    s.referral = {"referral_id": "REF-1", "recorded": True}
    msg = ta.gate(s, "refer_to_adjuster")
    assert msg and msg.startswith("BLOCKED") and "already" in msg


def test_prompt_sha_covers_the_tool_block():
    """S16: v1 and v2 reported one hash for different prompts because the tool block was left out."""
    assert ta.prompt_sha("tool A") != ta.prompt_sha("tool B")
    assert ta.prompt_sha("tool A") == ta.prompt_sha("tool A")
