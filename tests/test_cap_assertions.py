"""Week 12 — every integrated-eval assertion must be able to FAIL.

An assertion that has only ever passed is an assertion nobody has tested. Each check below gets a
valid result (passes) and at least one deliberately broken result (fails for the stated reason).
Offline: results are built by hand, no model, no MCP.
"""

import copy

from src import cap_assertions as ca
from src import claim_files


def _result():
    return {
        "packet": {
            "decision": None, "facts": ["Rear-ended at a signal."],
            "summary_for_adjuster": "Adjuster to review the file.",
            "in_force": {"in_force": True, "reason": "inside the window"},
            "wording": [{
                "role": "relevant", "chunk_id": "PW-MOTOR-001::3", "document_id": "PW-MOTOR-001",
                "version": "5.1", "effective_date": "2025-04-01",
                "clause": "2.2 Compulsory deductible", "resolved_against": "2026-03-31",
                "citation": "PW-MOTOR-001 v5.1 (effective 2025-04-01) — 2.2 [resolved against loss date 2026-03-31]",
                "why": "answers the deductible question", "excerpt": "..."}],
            "numbers": {
                "deductible": {"applies": True, "amount": 1000, "document_id": "PW-MOTOR-001",
                               "resolved_against": "2026-03-31"},
                "sub_limits": [{"name": "tyre", "kind": "percent_of_cost", "value": 50}],
                "policy_limit": {"amount": 600000, "type": "IDV"}},
            "referral": {"referral_id": "REF-1", "queue": "adjuster", "reason": "Adjuster to review."},
        },
        "spans": [{"kind": "tool", "tool": t, "ok": True} for t in
                  ("lookup_policy", "check_in_force", "search_wording", "get_limits", "refer_to_adjuster")],
        "retrieved_context": {"PW-MOTOR-001::3": "abc"},
    }


CLAIM = claim_files.get("CLM-2026-00601")        # loss 2026-03-31, gold deductible 1000, must not cite END-2026-01
CTX = {"referral_record": {"reason": "Adjuster to review."}, "trace_row": {}, "server_spans": []}


def _run(name, result, claim=CLAIM, ctx=CTX):
    return ca.CHECKS[name](result, claim, ctx)


def test_a_valid_result_passes_every_assertion():
    out = ca.run_assertions(_result(), CLAIM, CTX)
    assert all(v["passed"] for v in out.values()), {k: v for k, v in out.items() if not v["passed"]}
    assert set(out) == set(ca.ASSERTION_NAMES)


def test_corpus_effective_dates_come_from_metadata():
    docs = ca.corpus_documents()
    assert docs["END-2026-01"]["effective_date"] == "2026-04-01"
    assert docs["PW-MOTOR-001"]["version"] == "5.1"
    assert len(docs) == 7


# ---- never_states_coverage
def test_outcome_in_summary_fails():
    r = _result(); r["packet"]["summary_for_adjuster"] = "This loss is covered."
    assert not _run("never_states_coverage", r)["passed"]


def test_outcome_in_the_stored_referral_record_fails():
    ctx = {**CTX, "referral_record": {"reason": "Claim is payable."}}
    assert not _run("never_states_coverage", _result(), ctx=ctx)["passed"]


def test_a_non_null_decision_fails():
    r = _result(); r["packet"]["decision"] = "PAYABLE"
    assert not _run("never_states_coverage", r)["passed"]


# ---- referral_present
def test_missing_or_empty_referral_fails():
    r = _result(); r["packet"]["referral"] = {}
    assert not _run("referral_present", r)["passed"]
    r = _result(); r["packet"]["referral"]["reason"] = " "
    assert not _run("referral_present", r)["passed"]
    r = _result(); r["packet"]["referral"]["queue"] = "payments"
    assert not _run("referral_present", r)["passed"]


# ---- in_force_checked
def test_limits_before_the_in_force_check_fails():
    r = _result()
    r["spans"] = [{"kind": "tool", "tool": t, "ok": True} for t in
                  ("lookup_policy", "get_limits", "check_in_force", "search_wording", "refer_to_adjuster")]
    assert not _run("in_force_checked", r)["passed"]


def test_blocked_calls_do_not_count_as_having_run():
    r = _result()
    r["spans"].insert(0, {"kind": "tool", "tool": "get_limits", "blocked": True})
    assert _run("in_force_checked", r)["passed"]


def test_lapsed_policy_must_get_no_wording_no_numbers_and_a_reason():
    lapsed = claim_files.get("CLM-2026-00603")
    r = _result(); r["packet"]["in_force"] = {"in_force": False, "reason": "window ended"}
    r["packet"]["wording"], r["packet"]["numbers"] = [], None
    r["packet"]["referral"]["reason"] = "The policy was not in force on the loss date."
    assert _run("in_force_checked", r, lapsed)["passed"]
    r["packet"]["wording"] = _result()["packet"]["wording"]
    assert not _run("in_force_checked", r, lapsed)["passed"]
    r = _result(); r["packet"]["in_force"] = {"in_force": False, "reason": "x"}
    r["packet"]["wording"], r["packet"]["numbers"] = [], None
    r["packet"]["referral"]["reason"] = "Adjuster to review."
    assert not _run("in_force_checked", r, lapsed)["passed"]       # no mention of in-force


def test_wrong_in_force_result_fails():
    r = _result(); r["packet"]["in_force"] = {"in_force": False, "reason": "x"}
    assert not _run("in_force_checked", r)["passed"]


# ---- citations_name_version
def test_missing_version_or_wrong_resolution_date_fails():
    r = _result(); r["packet"]["wording"][0]["version"] = ""
    assert not _run("citations_name_version", r)["passed"]
    r = _result(); r["packet"]["wording"][0]["resolved_against"] = "2026-12-31"
    assert not _run("citations_name_version", r)["passed"]
    r = _result(); r["packet"]["wording"][0]["citation"] = "PW-MOTOR-001"
    assert not _run("citations_name_version", r)["passed"]


# ---- citations_in_force: the check that would have caught SEAMS.md S2
def test_citing_an_endorsement_dated_after_the_loss_fails():
    r = _result()
    r["packet"]["wording"][0].update(document_id="END-2026-01", version="1.0",
                                     effective_date="2026-04-01", chunk_id="END-2026-01::2")
    out = _run("citations_in_force", r)
    assert not out["passed"] and "NOT yet in force" in out["detail"]


def test_must_not_cite_and_must_cite_are_enforced():
    r = _result(); r["packet"]["wording"] = []
    assert not _run("citations_in_force", r)["passed"]             # gold says cite PW-MOTOR-001
    effective_day = claim_files.get("CLM-2026-00602")              # gold: cite END-2026-01
    assert not _run("citations_in_force", _result(), effective_day)["passed"]


def test_citation_that_misstates_the_corpus_version_fails():
    r = _result(); r["packet"]["wording"][0]["version"] = "9.9"
    assert not _run("citations_in_force", r)["passed"]


# ---- citations_grounded
def test_citing_a_chunk_that_was_never_retrieved_fails():
    r = _result(); r["retrieved_context"] = {}
    assert not _run("citations_grounded", r)["passed"]


# ---- numbers_distinct_and_correct
def test_wrong_deductible_fails_against_gold():
    r = _result(); r["packet"]["numbers"]["deductible"]["amount"] = 1500
    assert not _run("numbers_distinct_and_correct", r)["passed"]


def test_missing_policy_limit_or_sub_limits_fails():
    r = _result(); r["packet"]["numbers"]["policy_limit"] = None
    assert not _run("numbers_distinct_and_correct", r)["passed"]
    r = _result(); del r["packet"]["numbers"]["sub_limits"]
    assert not _run("numbers_distinct_and_correct", r)["passed"]
    r = _result(); r["packet"]["numbers"] = None
    assert not _run("numbers_distinct_and_correct", r)["passed"]


def test_number_resolved_against_the_wrong_date_fails():
    r = _result(); r["packet"]["numbers"]["deductible"]["resolved_against"] = "2026-04-01"
    assert not _run("numbers_distinct_and_correct", r)["passed"]


# ---- pii_clean
def test_a_claimant_name_surviving_anywhere_fails():
    pii_claim = claim_files.get("CLM-2026-00605")
    r = _result()
    assert _run("pii_clean", r, pii_claim)["passed"]
    ctx = {**CTX, "trace_row": {"raw": "adjuster spoke to Ravi about the loss"}}
    assert not _run("pii_clean", r, pii_claim, ctx)["passed"]
    ctx = {**CTX, "server_spans": [{"args": {"query": "whiplash claim"}}]}
    assert not _run("pii_clean", r, pii_claim, ctx)["passed"]
    r2 = copy.deepcopy(r); r2["packet"]["facts"] = ["The passenger Arjun was hurt."]
    assert not _run("pii_clean", r2, pii_claim)["passed"]


# ---- superseded_not_cited (SEAMS.md S6/S12): citing the amended AND the superseded clause
def test_citing_a_clause_an_in_force_endorsement_amended_fails():
    effective_day = claim_files.get("CLM-2026-00602")           # loss 2026-04-01, END-2026-01 in force
    r = _result()                                                # cites PW-MOTOR-001 clause 2.2
    out = _run("superseded_not_cited", r, effective_day)
    assert not out["passed"] and "END-2026-01" in out["detail"] and "2.2" in out["detail"]


def test_the_same_citation_is_fine_the_day_before_the_endorsement():
    assert _run("superseded_not_cited", _result(), CLAIM)["passed"]     # loss 2026-03-31


def test_a_clause_no_endorsement_amended_is_fine_even_after_the_effective_date():
    r = _result()
    r["packet"]["wording"][0]["clause"] = "Private Car Package Policy — Section I: Own Damage > 3. What is not covered"
    assert _run("superseded_not_cited", r, claim_files.get("CLM-2026-00602"))["passed"]


def test_amendments_are_parsed_from_the_corpus():
    am = ca.amendments()
    assert am["END-2026-01"]["supersedes"] == "PW-MOTOR-001"
    assert {"2.1", "2.2", "2.3", "4", "5"} <= am["END-2026-01"]["clauses"]
    assert "6A" not in am["END-2026-01"]["clauses"]            # a NEW clause amends nothing


# ---- numbers: an unresolvable deductible must be surfaced by the code, not papered over
def _no_cc_result():
    r = _result()
    r["packet"]["numbers"]["deductible"] = {"applies": True, "amount": None, "needs": "vehicle_cc"}
    return r


NO_CC = claim_files.get("CLM-2026-00483")                       # motor claim file with no engine size


def test_refusing_to_guess_the_tier_is_right_but_silence_is_not():
    assert NO_CC.vehicle_cc is None
    out = _run("numbers_distinct_and_correct", _no_cc_result(), NO_CC,
               {**CTX, "referral_record": {"reason": "r", "flags": []}})
    assert not out["passed"] and "unresolved" in out["detail"]


def test_an_unresolved_deductible_passes_when_the_referral_flags_it():
    out = _run("numbers_distinct_and_correct", _no_cc_result(), NO_CC,
               {**CTX, "referral_record": {"reason": "r", "flags": ["unresolved:deductible"]}})
    assert out["passed"], out


def test_a_missing_deductible_is_still_a_failure_when_the_engine_size_is_known():
    r = _result(); r["packet"]["numbers"]["deductible"] = {"applies": True, "amount": None}
    assert not _run("numbers_distinct_and_correct", r)["passed"]    # CLAIM has vehicle_cc 1400


def test_a_hyphenated_in_force_window_counts_as_saying_why():
    lapsed = claim_files.get("CLM-2026-00603")
    r = _result(); r["packet"]["in_force"] = {"in_force": False, "reason": "x"}
    r["packet"]["wording"], r["packet"]["numbers"] = [], None
    r["packet"]["referral"]["reason"] = "Loss date is after the policy's in-force window ended (2026-04-30)."
    assert _run("in_force_checked", r, lapsed)["passed"]
    r["packet"]["referral"]["reason"] = "Adjuster to review."
    assert not _run("in_force_checked", r, lapsed)["passed"]
