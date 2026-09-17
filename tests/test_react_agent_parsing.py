"""src/agent/react_agent.py — the parsing layer between raw model text and a real Action or
Final Answer. This is exactly the kind of regex/bracket-matching logic that breaks silently:
the module's own docstring explains _find_json_object exists because a naive regex "is a
losing game the moment a rationale string contains a brace or a colon" — so that is the first
thing tested here, not an afterthought.
"""

from __future__ import annotations

from src.agent.react_agent import _find_json_object, _parse_lap


# --------------------------------------------------------------------- _find_json_object


def test_find_json_object_simple_case():
    text = 'Thought: ok\nAction Input: {"claim_id": "C-001"}'
    obj, blob = _find_json_object(text, "Action Input")
    assert obj == {"claim_id": "C-001"}
    assert blob == '{"claim_id": "C-001"}'


def test_find_json_object_survives_braces_inside_a_string_value():
    """The exact scenario the module docstring calls out: a rationale that itself contains
    braces would break a naive `{.*}` regex but must not break bracket matching."""
    text = (
        'Final Answer: {"status": "NOT_PAYABLE", "payable_amount": null, '
        '"exclusion_clause": null, "rationale": "excluded under clause {3(a)} of the policy"}'
    )
    obj, _ = _find_json_object(text, "Final Answer")
    assert obj is not None
    assert obj["rationale"] == "excluded under clause {3(a)} of the policy"


def test_find_json_object_marker_not_found():
    obj, blob = _find_json_object("no marker here at all", "Final Answer")
    assert obj is None
    assert blob == ""


def test_find_json_object_no_opening_brace():
    obj, blob = _find_json_object("Final Answer: nothing but text", "Final Answer")
    assert obj is None


def test_find_json_object_malformed_json_reports_why():
    obj, err = _find_json_object('Action Input: {"claim_id": }', "Action Input")
    assert obj is None
    assert "did not parse" in err


def test_find_json_object_unclosed_brace():
    obj, err = _find_json_object('Action Input: {"claim_id": "C-001"', "Action Input")
    assert obj is None
    assert "no matching closing brace" in err


# --------------------------------------------------------------------- _parse_lap


def test_parse_lap_valid_action():
    raw = 'Thought: I need the claim file.\nAction: get_claim\nAction Input: {"claim_id": "C-001"}'
    parsed = _parse_lap(raw)
    assert parsed["kind"] == "action"
    assert parsed["tool"] == "get_claim"
    assert parsed["args"] == {"claim_id": "C-001"}


def test_parse_lap_valid_final_answer():
    raw = (
        'Thought: done.\nFinal Answer: {"status": "PAYABLE", "payable_amount": 7000.0, '
        '"exclusion_clause": null, "rationale": "covered"}'
    )
    parsed = _parse_lap(raw)
    assert parsed["kind"] == "final"
    assert parsed["answer"]["status"] == "PAYABLE"


def test_parse_lap_final_answer_missing_required_field_is_malformed():
    raw = 'Final Answer: {"status": "PAYABLE", "payable_amount": 7000.0}'
    parsed = _parse_lap(raw)
    assert parsed["kind"] == "malformed"
    assert "missing fields" in parsed["error"]


def test_parse_lap_final_answer_invalid_status_is_malformed():
    raw = (
        'Final Answer: {"status": "MAYBE", "payable_amount": null, '
        '"exclusion_clause": null, "rationale": "unsure"}'
    )
    parsed = _parse_lap(raw)
    assert parsed["kind"] == "malformed"
    assert "status must be one of" in parsed["error"]


def test_parse_lap_no_action_and_no_final_answer_is_malformed():
    parsed = _parse_lap("Thought: I am thinking about it.")
    assert parsed["kind"] == "malformed"


def test_parse_lap_action_with_unparseable_input_is_malformed():
    raw = "Thought: ok\nAction: get_claim\nAction Input: not json at all"
    parsed = _parse_lap(raw)
    assert parsed["kind"] == "malformed"
