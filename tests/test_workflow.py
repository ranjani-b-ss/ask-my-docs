"""src/agent/workflow.py's pure helpers — no LLM calls needed to test any of these, and every
one of them is where a real Week 7 bug actually lived: _current_deductible picked the wrong
clause and the wrong cc bracket, _exclusion_query never fired for an unrecognised fact pattern,
_majority_decision needed to fail safe on a tie. These tests pin the FIXED behavior so a future
edit can't silently reopen one of them.
"""

from __future__ import annotations

from src.agent.workflow import (
    _current_deductible,
    _exclusion_query,
    _is_known_unresolvable,
    _majority_decision,
    _GENERAL_EXCLUSION_QUERY,
)


# --------------------------------------------------------------------- _exclusion_query


def test_exclusion_query_matches_drink_driving():
    query = _exclusion_query("the driver failed a breathalyzer test at the scene")
    assert "intoxicating liquor" in query


def test_exclusion_query_matches_tyres():
    query = _exclusion_query("both nearside tyres burst after the pothole")
    assert "tyres" in query


def test_exclusion_query_falls_back_to_general_when_nothing_matches():
    """This exact gap — no keyword match meant no exclusion check at all — was WEEK7's C-008
    bug. The fix was making the fallback a real query instead of skipping the check."""
    query = _exclusion_query("a tree branch fell on the parked car overnight")
    assert query == _GENERAL_EXCLUSION_QUERY


def test_exclusion_query_is_case_insensitive():
    query = _exclusion_query("DRIVING UNDER THE INFLUENCE, blood alcohol confirmed")
    assert query != _GENERAL_EXCLUSION_QUERY


# --------------------------------------------------------------------- _is_known_unresolvable


def test_is_known_unresolvable_true_for_hydrolock():
    # \bhydrolock\b matches the bare word only — "hydrolocked" does not have a word boundary
    # right after "hydrolock", so it does NOT match on its own. Confirmed this isn't a live
    # bug: the real C-010 claim's notes also contain "flooded underpass" (tested below),
    # which is what actually trips the pattern in production.
    assert _is_known_unresolvable("the engine suffered a hydrolock event") is True


def test_is_known_unresolvable_true_for_flooded_underpass():
    """The real C-010 claim text says "hydrolocked" (past tense, does not match \\bhydrolock\\b
    on its own) but also says "flooded underpass" — that's the phrase carrying the match in
    production. Both alternatives are tested so a future edit to either doesn't go unnoticed."""
    assert _is_known_unresolvable("drove into a flooded underpass against a barricade") is True


def test_is_known_unresolvable_false_for_ordinary_claim():
    assert _is_known_unresolvable("rear-ended at a red light, not at fault") is False


# --------------------------------------------------------------------- _current_deductible


def test_current_deductible_picks_latest_effective_date_not_top_rank():
    """The exact Week 7 bug: the reranker can put the base clause above a later endorsement
    regardless of the claim's date. This function must ignore rank and pick by date."""
    hits = [
        {"document_id": "PW-MOTOR-001", "effective_date": "2025-04-01",
         "text": "INR 1,000 up to 1500cc, and INR 2,000 for vehicles above 1500cc"},
        {"document_id": "END-2026-01", "effective_date": "2026-04-01",
         "text": "INR 1,500 up to 1500cc, and INR 3,000 for vehicles above 1500cc"},
    ]
    # Loss date is AFTER the endorsement took effect — the endorsement must win even though
    # it's listed second (i.e. lower-ranked) here.
    assert _current_deductible(hits, date_of_loss="2026-06-01", vehicle_cc=1400) == 1500.0


def test_current_deductible_ignores_endorsement_not_yet_in_force():
    hits = [
        {"document_id": "PW-MOTOR-001", "effective_date": "2025-04-01",
         "text": "INR 1,000 up to 1500cc, and INR 2,000 for vehicles above 1500cc"},
        {"document_id": "END-2026-01", "effective_date": "2026-04-01",
         "text": "INR 1,500 up to 1500cc, and INR 3,000 for vehicles above 1500cc"},
    ]
    # Loss date is BEFORE the endorsement's effective date — base wording still governs.
    assert _current_deductible(hits, date_of_loss="2026-01-01", vehicle_cc=1400) == 1000.0


def test_current_deductible_picks_correct_cc_bracket():
    """The second Week 7 bug: taking the first INR figure regardless of vehicle size."""
    hits = [{"document_id": "PW-MOTOR-001", "effective_date": "2025-04-01",
            "text": "INR 1,000 up to 1500cc, and INR 2,000 for vehicles above 1500cc"}]
    assert _current_deductible(hits, date_of_loss="2026-01-01", vehicle_cc=1500) == 1000.0
    assert _current_deductible(hits, date_of_loss="2026-01-01", vehicle_cc=1800) == 2000.0


def test_current_deductible_no_candidates_returns_zero():
    assert _current_deductible([], date_of_loss="2026-01-01", vehicle_cc=1400) == 0.0


def test_current_deductible_ignores_irrelevant_documents():
    hits = [{"document_id": "END-2026-02", "effective_date": "2026-05-01",
            "text": "some unrelated health endorsement clause"}]
    assert _current_deductible(hits, date_of_loss="2026-06-01", vehicle_cc=1400) == 0.0


# --------------------------------------------------------------------- _majority_decision


def test_majority_decision_clear_majority_wins():
    votes = [
        {"status": "NOT_PAYABLE", "rationale": "a"},
        {"status": "NOT_PAYABLE", "rationale": "b"},
        {"status": "PAYABLE", "rationale": "c"},
    ]
    result = _majority_decision(votes, claim_amount=5000.0)
    assert result["status"] == "NOT_PAYABLE"
    assert "2/3" in result["rationale"]


def test_majority_decision_tie_fails_safe_to_referred():
    votes = [
        {"status": "PAYABLE", "rationale": "a"},
        {"status": "NOT_PAYABLE", "rationale": "b"},
    ]
    result = _majority_decision(votes, claim_amount=5000.0)
    assert result["status"] == "REFERRED"


def test_majority_decision_no_votes_fails_safe_to_referred():
    result = _majority_decision([], claim_amount=5000.0)
    assert result["status"] == "REFERRED"
    assert result["claim_amount_for_payout"] == 5000.0
