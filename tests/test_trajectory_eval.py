"""eval/trajectory_eval.py's own scoring logic — the Week 8 deliverable, tested against
synthetic trace rows so the eval tool's correctness doesn't rest solely on "it produced
numbers that looked right once." Real claim ids (C-001, C-007) are used because
sequence_check/classify_modes look their expected-sequence spec up by id.
"""

from __future__ import annotations

import json

from eval.trajectory_eval import argument_check, classify_modes, sequence_check


def _search_step(document_id: str, text: str = "") -> dict:
    return {
        "tool": "search_policy",
        "parsed": {"kind": "action"},
        "observation": json.dumps([{"document_id": document_id, "text": text}]),
    }


def _tool_step(tool: str, tool_args: dict) -> dict:
    return {"tool": tool, "parsed": {"kind": "action"}, "tool_args": tool_args}


# --------------------------------------------------------------------- sequence_check


def test_sequence_check_passes_the_minimal_valid_path():
    tools = ["get_claim", "search_policy", "compute_payout"]
    ok, reason = sequence_check("C-001", tools)
    assert ok, reason


def test_sequence_check_fails_when_get_claim_is_not_first():
    ok, reason = sequence_check("C-001", ["search_policy", "get_claim", "compute_payout"])
    assert not ok
    assert "first" in reason


def test_sequence_check_fails_when_search_policy_is_skipped():
    ok, reason = sequence_check("C-001", ["get_claim", "compute_payout"])
    assert not ok
    assert "search_policy" in reason


def test_sequence_check_fails_when_compute_payout_is_skipped():
    """This is Week 8's own flagship failure mode: C-003/004/005/006/009/010 all failed
    exactly this check before the mitigation."""
    ok, reason = sequence_check("C-001", ["get_claim", "search_policy"])
    assert not ok
    assert "compute_payout" in reason


def test_sequence_check_fails_when_tools_present_but_out_of_order():
    ok, reason = sequence_check("C-001", ["get_claim", "compute_payout", "search_policy"])
    assert not ok
    assert "out of order" in reason


def test_sequence_check_c007_needs_two_search_calls():
    """C-007's compound hire-car exclusion is the one documented case needing an extra
    search_policy call (see EXPECTED_SEQUENCES's own docstring in trajectory_eval.py)."""
    ok, reason = sequence_check("C-007", ["get_claim", "search_policy", "compute_payout"])
    assert not ok
    assert "search_policy" in reason

    ok, _ = sequence_check(
        "C-007", ["get_claim", "search_policy", "search_policy", "compute_payout"]
    )
    assert ok


# --------------------------------------------------------------------- argument_check


def test_argument_check_passes_when_citation_matches_a_retrieved_document():
    row = {
        "exclusion_clause": "PW-MOTOR-001 Section I, Clause 3",
        "steps": [
            {"tool": "get_claim", "tool_args": {"claim_id": "C-001"}},
            _search_step("PW-MOTOR-001", "INR 1,000 deductible"),
        ],
    }
    ok, reason = argument_check({}, row)
    assert ok, reason


def test_argument_check_fails_on_a_citation_to_a_document_never_retrieved():
    """This is exactly C-003's real, verified bug: citing POL-GEN-2024 after zero
    search_policy calls."""
    row = {
        "exclusion_clause": "POL-GEN-2024 Clause 4.2",
        "steps": [{"tool": "get_claim", "tool_args": {"claim_id": "C-001"}}],
    }
    ok, reason = argument_check({}, row)
    assert not ok
    assert "search_policy was never called" in reason


def test_argument_check_fails_on_unknown_claim_id():
    row = {"steps": [{"tool": "get_claim", "tool_args": {"claim_id": "C-999"}}]}
    ok, reason = argument_check({}, row)
    assert not ok
    assert "unknown claim_id" in reason


def test_argument_check_fails_on_invented_deductible():
    """The post-mitigation regression from WEEK8.md §7: compute_payout called for real, but
    with a deductible figure that never appeared in any search_policy result."""
    row = {
        "steps": [
            _search_step("PW-MOTOR-001", "no deductible figure mentioned here"),
            {"tool": "compute_payout", "tool_args": {"deductible": 1000.0, "status": "NOT_PAYABLE"}},
        ],
    }
    ok, reason = argument_check({}, row)
    assert not ok
    assert "never appeared" in reason


def test_argument_check_passes_when_deductible_is_grounded():
    row = {
        "steps": [
            _search_step("PW-MOTOR-001", "compulsory deductible of INR 1,000 applies"),
            {"tool": "compute_payout", "tool_args": {"deductible": 1000.0, "status": "NOT_PAYABLE"}},
        ],
    }
    ok, reason = argument_check({}, row)
    assert ok, reason


def test_argument_check_passes_with_no_exclusion_clause_and_no_payout_call():
    """Vacuously fine — nothing to check when neither field is present."""
    row = {"steps": [{"tool": "get_claim", "tool_args": {"claim_id": "C-001"}}]}
    ok, reason = argument_check({}, row)
    assert ok, reason


# --------------------------------------------------------------------- classify_modes


def test_classify_modes_flags_skipped_mandatory_tool():
    row = {"status": "NOT_PAYABLE", "exclusion_clause": None,
          "steps": [_tool_step("get_claim", {"claim_id": "C-001"})]}
    assert "skipped_mandatory_tool" in classify_modes("C-001", row)


def test_classify_modes_flags_redundant_search_loop():
    row = {
        "status": "PAYABLE", "exclusion_clause": None,
        "steps": [
            _tool_step("get_claim", {"claim_id": "C-001"}),
            _search_step("PW-MOTOR-001"),
            _search_step("PW-MOTOR-001"),
            _search_step("PW-MOTOR-001"),
            _tool_step("compute_payout", {"deductible": 0}),
        ],
    }
    assert "redundant_search_loop" in classify_modes("C-001", row)


def test_classify_modes_flags_hallucinated_tool_call():
    """A rejected Final Answer whose own text contains 'Observation:' — the model narrating
    a tool call it never actually dispatched. See WEEK8.md §6.1/§6.2 for the real cases."""
    row = {
        "status": "PAYABLE", "exclusion_clause": None,
        "steps": [
            _tool_step("get_claim", {"claim_id": "C-001"}),
            _search_step("PW-MOTOR-001"),
            {
                "parsed": {"kind": "final"},
                "payout_verified": False,
                "raw_output": 'Thought: done. Observation: 7000.0\nFinal Answer: {"status": "PAYABLE"}',
            },
        ],
    }
    assert "hallucinated_tool_call" in classify_modes("C-001", row)


def test_classify_modes_reports_none_for_a_clean_run():
    row = {
        "status": "NOT_PAYABLE", "exclusion_clause": "PW-MOTOR-001 Section I, Clause 3",
        "steps": [
            _tool_step("get_claim", {"claim_id": "C-001"}),
            _search_step("PW-MOTOR-001", "INR 1,000 deductible"),
            _tool_step("compute_payout", {"deductible": 1000.0, "status": "NOT_PAYABLE"}),
        ],
    }
    assert classify_modes("C-001", row) == []
