"""Week 12 — the "never states a coverage decision" guard (src/triage_guard.py).

The brief's hostile question: "show me the assertion that enforces that, not the prompt that
asks for it." These tests are that assertion, plus the cases where it must stay quiet.
"""

import pytest

from src.triage_guard import guard_fields, states_coverage


@pytest.mark.parametrize("text", [
    "This loss is covered under the policy.",
    "The claim is payable once the surveyor reports.",
    "The claim will be paid in full.",
    "We should settle this one quickly.",
    "Recommend the claim be approved.",
    "This claim should be declined.",
    "The flood damage is excluded.",
    "The insured is entitled to the full amount.",
    "Claim denied on the licence exclusion.",
])
def test_outcome_statements_are_caught(text):
    assert states_coverage(text), text


@pytest.mark.parametrize("text", [
    "The driver reportedly did not hold a valid licence at the time.",
    "Clause 3 lists a licence exclusion that the adjuster should weigh against these facts.",
    "Loss date 2026-03-31 falls before END-2026-01 took effect.",
    "Referring to an adjuster: the facts make an exclusion arguable.",
    "",
    None,
])
def test_neutral_text_passes(text):
    assert states_coverage(text) == []


def test_quoted_wording_is_not_checked():
    # A clause title legitimately contains the word; quoting the policy is not stating an outcome.
    assert states_coverage('Clause 3, "What is not covered", is arguable on these facts.') == []
    assert states_coverage("Clause 3, “What is not covered”, is arguable here.") == []


def test_a_violating_field_is_replaced_and_recorded():
    safe, violations = guard_fields({"summary": "The loss is covered.",
                                     "facts": ["Rear-ended at a signal", "This is payable"]})
    assert "covered" not in safe["summary"].lower()
    assert safe["facts"][0] == "Rear-ended at a signal"
    assert "payable" not in safe["facts"][1].lower()
    assert {v["field"] for v in violations} == {"summary", "facts[1]"}


def test_clean_fields_pass_through_unchanged():
    fields = {"summary": "Rear-ended at a signal; adjuster to review.", "facts": ["a", "b"]}
    safe, violations = guard_fields(fields)
    assert safe == fields and violations == []
