"""src/assertions.py — Week 6's whole thesis: "if you can write it as a predicate over the
text, it does not belong to a judge." These are exactly those predicates, and exactly the
kind of regex logic that looks obviously right and is subtly wrong on a real edge case.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.assertions import (
    assert_claim_number,
    assert_date_of_loss,
    assert_deductible_numeric,
    assert_exclusion_cited_on_denial,
    citations_resolve,
)
from src.retriever import Hit
from src.summariser import Summary


def _summary(fields: dict, hits: list[Hit] | None = None, text: str = "x") -> Summary:
    return Summary(case_id="test", text=text, fields=fields, hits=hits or [])


# --------------------------------------------------------------------- A1 claim number


def test_claim_number_passes_when_it_matches_the_case():
    s = _summary({"claim number": "CLM-2026-04871"})
    check = assert_claim_number(s, {"notes": "re: CLM-2026-04871"})
    assert check.passed


def test_claim_number_fails_on_wrong_format():
    s = _summary({"claim number": "CLM-26-412"})
    check = assert_claim_number(s, {})
    assert not check.passed


def test_claim_number_fails_when_it_belongs_to_a_different_claim():
    """Worse than malformed: well-formed but wrong. The assertion module's own docstring
    calls this out explicitly."""
    s = _summary({"claim number": "CLM-2026-11111"})
    check = assert_claim_number(s, {"notes": "claim CLM-2026-04871 filed"})
    assert not check.passed
    assert "04871" in check.detail


def test_claim_number_fails_when_missing():
    s = _summary({})
    check = assert_claim_number(s, {})
    assert not check.passed


# --------------------------------------------------------------------- A2 date of loss


def test_date_of_loss_passes_on_valid_past_date():
    check = assert_date_of_loss(_summary({"date of loss": "2026-01-15"}), {})
    assert check.passed


def test_date_of_loss_fails_in_the_future():
    future = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
    check = assert_date_of_loss(_summary({"date of loss": future}), {})
    assert not check.passed
    assert "future" in check.detail


def test_date_of_loss_fails_when_unparseable():
    check = assert_date_of_loss(_summary({"date of loss": "sometime last spring"}), {})
    assert not check.passed


# --------------------------------------------------------------------- A3 deductible


def test_deductible_passes_on_numeric_amount():
    check = assert_deductible_numeric(_summary({"deductible": "INR 1,000"}), {})
    assert check.passed


def test_deductible_passes_on_explicit_none():
    check = assert_deductible_numeric(_summary({"deductible": "None"}), {})
    assert check.passed


def test_deductible_fails_on_non_numeric_garbage():
    check = assert_deductible_numeric(_summary({"deductible": "to be determined"}), {})
    assert not check.passed


# --------------------------------------------------------------------- A4 exclusion on denial


def test_denial_with_clause_and_retrieved_document_passes():
    hits = [Hit(text="...", meta={"document_id": "PW-MOTOR-001"}, cosine=0.5)]
    s = _summary({"position": "NOT PAYABLE",
                  "exclusion relied on": "PW-MOTOR-001 Clause 3"}, hits=hits)
    check = assert_exclusion_cited_on_denial(s, {})
    assert check.passed


def test_denial_with_no_exclusion_named_fails():
    s = _summary({"position": "NOT PAYABLE", "exclusion relied on": "None"})
    check = assert_exclusion_cited_on_denial(s, {})
    assert not check.passed
    assert "no exclusion clause" in check.detail


def test_payable_that_also_cites_an_exclusion_fails():
    """Self-contradiction: a PAYABLE summary should not also cite an exclusion clause."""
    s = _summary({"position": "PAYABLE", "exclusion relied on": "PW-MOTOR-001 Clause 3"})
    check = assert_exclusion_cited_on_denial(s, {})
    assert not check.passed


def test_denial_citing_a_document_never_retrieved_fails():
    hits = [Hit(text="...", meta={"document_id": "PW-MOTOR-001"}, cosine=0.5)]
    s = _summary({"position": "NOT PAYABLE",
                  "exclusion relied on": "END-2026-01 Clause 7"}, hits=hits)
    check = assert_exclusion_cited_on_denial(s, {})
    assert not check.passed


# --------------------------------------------------------------------- citations_resolve


def test_citations_resolve_passes_for_valid_markers():
    hits = [Hit(text="a", meta={}, cosine=0.5), Hit(text="b", meta={}, cosine=0.5)]
    s = _summary({}, hits=hits, text="Basis: covered per [1] and [2].")
    s.fields["basis"] = "covered per [1] and [2]"
    check = citations_resolve(s)
    assert check.passed


def test_citations_resolve_fails_on_invented_marker():
    hits = [Hit(text="a", meta={}, cosine=0.5)]
    s = _summary({}, hits=hits, text="x")
    s.fields["basis"] = "covered per [1] and [5]"
    check = citations_resolve(s)
    assert not check.passed
    assert "5" in check.detail


def test_citations_resolve_fails_when_no_markers_at_all():
    s = _summary({}, hits=[Hit(text="a", meta={}, cosine=0.5)], text="no citations here")
    check = citations_resolve(s)
    assert not check.passed
