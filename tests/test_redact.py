"""src/redact.py — the one thing this suite cannot afford to get wrong quietly.

Week 5 built this to keep claimant PII out of trace files; Week 8 found it wasn't actually
being applied on the agent's own trace writer (src/agent/trace.py). These tests exist so that
kind of gap gets caught by `pytest`, not by re-reading the source months later.
"""

from __future__ import annotations

from src import redact


def test_scrub_redacts_email():
    assert redact.scrub("contact rajesh@example.com for details") == \
        "contact [REDACTED] for details"


def test_scrub_redacts_phone():
    out = redact.scrub("mobile 98765 43210 on file")
    assert "98765" not in out
    assert "[REDACTED]" in out


def test_scrub_redacts_aadhaar():
    out = redact.scrub("Aadhaar 1234 5678 9012 provided")
    assert "1234 5678 9012" not in out


def test_scrub_redacts_pan():
    out = redact.scrub("PAN ABCDE1234F on record")
    assert "ABCDE1234F" not in out


def test_scrub_redacts_claim_number():
    out = redact.scrub("claim no. CLM-2026-004871 was filed")
    assert "CLM-2026-004871" not in out


def test_scrub_redacts_titled_name():
    out = redact.scrub("Claimant Mr. Rajesh Kumar reported the loss")
    assert "Rajesh Kumar" not in out


def test_scrub_preserves_policy_amounts():
    """The whole point of Week 6's assertions is that a redaction pass must not eat the
    numbers an adjuster actually needs — see eval/check_redaction.py's own "policy figures
    preserved" check, which this mirrors at the unit level."""
    for amount in ("Rs. 10,000", "INR 500000", "the deductible is 1,000"):
        assert amount in redact.scrub(f"the amount is {amount} as stated"), amount


def test_scrub_is_idempotent():
    text = "Claimant Mr. Rajesh Kumar, mobile 98765 43210, claim CLM-2026-004871"
    once = redact.scrub(text)
    twice = redact.scrub(once)
    assert once == twice


def test_scrub_none_and_empty_are_safe():
    assert redact.scrub(None) is None
    assert redact.scrub("") == ""


def test_scrub_deep_recurses_through_nested_structures():
    payload = {
        "claim_id": "C-001",          # not PII — must survive
        "notes": "contact rajesh@example.com",
        "amount": 8000.0,             # non-string — must pass through untouched
        "steps": [
            {"tool_args": {"claim_id": "C-001"}, "observation": "PAN ABCDE1234F"},
        ],
    }
    out = redact.scrub_deep(payload)
    assert out["claim_id"] == "C-001"
    assert out["amount"] == 8000.0
    assert "rajesh@example.com" not in out["notes"]
    assert out["steps"][0]["tool_args"]["claim_id"] == "C-001"
    assert "ABCDE1234F" not in out["steps"][0]["observation"]


def test_scrub_deep_leaves_non_string_leaves_alone():
    assert redact.scrub_deep(42) == 42
    assert redact.scrub_deep(None) is None
    assert redact.scrub_deep(3.14) == 3.14


def test_contains_identifier_true_and_false():
    assert redact.contains_identifier("email me at rajesh@example.com") is True
    assert redact.contains_identifier("the deductible is Rs. 10,000") is False
    assert redact.contains_identifier(None) is False


def test_scrub_has_a_known_false_positive_on_policy_document_ids():
    """Documented, not silently fixed (see WEEK8's redaction-fix follow-up). "Policy" is one
    of _CLAIM_ID's trigger prefixes, built for real policy/claim numbers like POL-2024-1871 —
    it cannot tell that apart from an internal document id like PW-MOTOR-001 when the word
    "Policy" happens to sit right before it. This test pins the CURRENT behavior so a future
    change to the regex is a deliberate decision, not an accidental side effect."""
    out = redact.scrub("per Policy PW-MOTOR-001 this is excluded")
    assert "PW-MOTOR-001" not in out          # current (imperfect) behavior
    # A bare document id with no trigger word in front is unaffected:
    assert "PW-MOTOR-001" in redact.scrub("see PW-MOTOR-001 for the full clause")
