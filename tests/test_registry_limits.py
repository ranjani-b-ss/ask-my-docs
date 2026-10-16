"""Week 12 — claim-file index, policy registry / in-force check, effective-dated limits.

All offline and deterministic. The corpus-figure test is the important one: the limits table is
hand-transcribed, so it is checked against the real wording files, and a transcription slip
fails here instead of on a claim.
"""

from pathlib import Path

import pytest

from src import claim_files, limits, registry

CORPUS = Path(__file__).resolve().parent.parent / "corpora" / "insurance"


# ------------------------------------------------------------------ claim-file index (S5)

def test_all_three_sources_load_with_no_duplicate_numbers():
    idx = claim_files.load_all()
    assert len(idx) == 47
    by_source = {}
    for cf in idx.values():
        by_source[cf.source] = by_source.get(cf.source, 0) + 1
    assert by_source == {"claims_store": 11, "week6": 27, "capstone": 9}


def test_week6_claim_file_parses():
    cf = claim_files.get("CLM-2026-00418")
    assert (cf.product, cf.loss_date, cf.insured_age) == ("health", "2026-04-02", 44)
    assert "abdominal pain" in cf.narrative
    assert "Which expenses are permanently excluded" in cf.coverage_question


def test_agent_claim_carries_vehicle_cc():
    cf = claim_files.get("C-002")
    assert (cf.product, cf.vehicle_cc, cf.loss_date) == ("motor", 1800, "2026-06-01")


def test_unknown_claim_raises():
    with pytest.raises(KeyError):
        claim_files.get("NOPE-1")


# ------------------------------------------------------------------ in-force check

def _policy(claim):
    return registry.policy_for_claim(claim)["policy_number"]


def test_in_force_window_is_inclusive_at_both_ends():
    pol = _policy("C-001")                           # window 2025-10-01 .. 2026-09-30
    assert registry.check_in_force(pol, "2025-10-01")["in_force"] is True
    assert registry.check_in_force(pol, "2026-09-30")["in_force"] is True
    assert registry.check_in_force(pol, "2025-09-30")["in_force"] is False
    assert registry.check_in_force(pol, "2026-10-01")["in_force"] is False


def test_lapsed_policy_is_refused_and_says_why():
    pol = _policy("CLM-2026-00603")
    r = registry.check_in_force(pol, "2026-05-20")
    assert r["in_force"] is False
    assert "after the policy's in-force window ended (2026-04-30)" in r["reason"]


def test_not_yet_incepted_policy_is_refused_and_says_why():
    pol = _policy("CLM-2026-00604")
    r = registry.check_in_force(pol, "2026-02-10")
    assert r["in_force"] is False
    assert "before the policy's in-force window began (2026-03-01)" in r["reason"]


def test_unknown_policy_number_is_not_in_force():
    r = registry.check_in_force("MOT-9999-0000", "2026-01-01")
    assert r["in_force"] is False and "not in the registry" in r["reason"]


def test_every_claim_file_has_exactly_one_policy():
    for number in claim_files.load_all():
        assert registry.policy_for_claim(number) is not None, number


# ------------------------------------------------------------------ limits: which row governs

def test_deductible_flips_on_the_endorsements_effective_day():
    before = limits.get_limits("motor", "2026-03-31", vehicle_cc=1400)["deductible"]
    on = limits.get_limits("motor", "2026-04-01", vehicle_cc=1400)["deductible"]
    assert (before["amount"], before["document_id"]) == (1000, "PW-MOTOR-001")
    assert (on["amount"], on["document_id"]) == (1500, "END-2026-01")
    assert before["resolved_against"] == "2026-03-31" and on["resolved_against"] == "2026-04-01"


def test_deductible_tiers_by_engine_size():
    assert limits.get_limits("motor", "2026-03-31", 1500)["deductible"]["amount"] == 1000
    assert limits.get_limits("motor", "2026-03-31", 1501)["deductible"]["amount"] == 2000
    assert limits.get_limits("motor", "2026-06-01", 1500)["deductible"]["amount"] == 1500
    assert limits.get_limits("motor", "2026-06-01", 1800)["deductible"]["amount"] == 3000


def test_missing_engine_size_is_asked_for_not_guessed():
    d = limits.get_limits("motor", "2026-06-01")["deductible"]
    assert d["amount"] is None and d["needs"] == "vehicle_cc"


def test_loss_before_any_wording_was_in_force():
    d = limits.get_limits("motor", "2025-03-31", 1400)["deductible"]
    assert d["applies"] is False


def test_copayment_depends_on_both_version_and_age():
    base = limits.get_limits("health", "2026-04-30", insured_age=63)["co_payment"]
    amended = limits.get_limits("health", "2026-05-01", insured_age=63)["co_payment"]
    assert (base["applies"], base["percent"], base["document_id"]) == (True, 20, "PW-HEALTH-002")
    # the endorsement raised the age to 66, so a 63-year-old no longer pays any co-payment
    assert (amended["applies"], amended["percent"], amended["document_id"]) == (False, None, "END-2026-02")
    assert limits.get_limits("health", "2026-05-01", insured_age=66)["co_payment"]["percent"] == 10


def test_health_has_no_deductible_and_says_so():
    d = limits.get_limits("health", "2026-04-30")["deductible"]
    assert d["applies"] is False and "co-payment" in d["reason"]


def test_three_numbers_stay_three_different_things():
    pol = registry.policy_for_claim("CLM-2026-00606")
    out = limits.get_limits("motor", "2026-06-15", 1400, policy=pol)
    assert out["deductible"]["amount"] == 1500                       # INR, from the wording
    assert out["sub_limits"][0]["value"] == 50                        # a percentage of tyre cost
    assert out["policy_limit"]["amount"] == 600000                    # the IDV, from the policy
    assert len({out["deductible"]["amount"], out["sub_limits"][0]["value"],
                out["policy_limit"]["amount"]}) == 3


def test_room_rent_sub_limit_is_a_function_of_version_and_sum_insured():
    pol = registry.policy_for_claim("CLM-2026-00609")                 # sum insured 5,00,000
    base = limits.get_limits("health", "2026-04-30", policy=pol)["sub_limits"][0]
    amended = limits.get_limits("health", "2026-05-01", policy=pol)["sub_limits"][0]
    assert (base["amount_per_day"], base["proportionate_deduction"]) == (5000, True)
    assert (amended["amount_per_day"], amended["proportionate_deduction"]) == (10000, False)


def test_unknown_product_is_rejected():
    with pytest.raises(ValueError):
        limits.get_limits("household", "2026-01-01")


# ------------------------------------------------------------------ the table matches the wording

WORDING = {
    "PW-MOTOR-001": CORPUS / "policy-wording" / "01-motor-own-damage.md",
    "END-2026-01": CORPUS / "endorsements" / "END-2026-01-motor.md",
    "PW-HEALTH-002": CORPUS / "policy-wording" / "02-health-indemnity.md",
    "END-2026-02": CORPUS / "endorsements" / "END-2026-02-health.md",
}

# (document, literal text that must appear in that document's file)
FIGURES = [
    ("PW-MOTOR-001", "**INR 1,000**"), ("PW-MOTOR-001", "**INR 2,000**"),
    ("END-2026-01", "**INR 1,500**"), ("END-2026-01", "**INR 3,000**"),
    ("PW-MOTOR-001", "limited to **50% of the cost of replacement**"),
    ("PW-HEALTH-002", "co-payment of **20%**"), ("PW-HEALTH-002", "61 years"),
    ("END-2026-02", "**66 years**"), ("END-2026-02", "**10%**"),
    ("PW-HEALTH-002", "**1% of the sum insured per day**"),
    ("END-2026-02", "**2% of the sum insured per day**"),
]


@pytest.mark.parametrize("doc,literal", FIGURES)
def test_every_table_figure_is_in_the_wording_it_cites(doc, literal):
    assert literal in " ".join(WORDING[doc].read_text(encoding="utf-8").split())


def test_every_cited_document_version_matches_the_corpus_metadata():
    import re
    for doc, path in WORDING.items():
        head = path.read_text(encoding="utf-8")[:600]
        ver = re.search(r'^version:\s*"?([\d.]+)"?', head, re.M).group(1)
        table = limits._table()
        rows = [r for prod in table.values() for key in ("deductible", "co_payment", "sub_limits")
                for r in (prod.get(key) or []) if r["source"]["document_id"] == doc]
        assert rows, f"no table row cites {doc}"
        assert all(r["source"]["version"] == ver for r in rows), (doc, ver)
