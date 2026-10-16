"""Week 12 — claimant-text redaction: names, ADDRESSES and INJURIES (SEAMS.md S8).

The client's PII line is claimant names, addresses and injuries, on the logs and on anything
an MCP server returns. These tests pin what is caught and, just as important, what must NOT
be touched: amounts, dates, claim and policy numbers, and policy wording.
"""

from src import redact

FNOL_1 = ("Claimant Ravi Kumar Sharma, residing at 14 MG Road, Indiranagar, Bengaluru 560038, "
          "phone 98450 12345, reports whiplash and a fractured left wrist after the other "
          "driver rear-ended the insured vehicle.")
FNOL_2 = ("Insured Priya Menon of Flat 3B, Lakshmi Apartments, 2nd Cross, Adyar, Chennai "
          "600020 was driving; her passenger Arjun Nair suffered a head injury and three "
          "broken ribs.")
FNOL_3 = ("Policyholder: Mrs. Sunita Rao. Address: H.No 7-1-24, Begumpet, Hyderabad - 500016. "
          "Injury: deep laceration to the right forearm. Email sunita.rao@example.com.")


def test_names_addresses_injuries_all_gone_from_a_realistic_fnol():
    out = redact.scrub_claimant(FNOL_1)
    for leaked in ("Ravi", "Sharma", "MG Road", "Indiranagar", "560038", "98450",
                   "whiplash", "fractured"):
        assert leaked not in out, f"{leaked!r} survived: {out}"


def test_second_person_introduced_by_passenger_is_caught():
    out = redact.scrub_claimant(FNOL_2)
    for leaked in ("Priya", "Menon", "Arjun", "Nair", "Lakshmi", "Adyar", "600020",
                   "head injury", "broken ribs"):
        assert leaked not in out, f"{leaked!r} survived: {out}"


def test_cued_address_and_injury_lines():
    out = redact.scrub_claimant(FNOL_3)
    for leaked in ("Sunita", "Begumpet", "500016", "laceration", "sunita.rao"):
        assert leaked not in out, f"{leaked!r} survived: {out}"


def test_address_stops_at_its_pin_and_does_not_eat_the_sentence():
    out = redact.scrub_claimant(FNOL_1)
    assert "the other driver rear-ended the insured vehicle" in out


def test_registered_to_introduces_a_name():
    out = redact.scrub_claimant("Vehicle registered to Anita Desai at 9/2 Park Street, "
                                "Kolkata - 700016.")
    assert "Anita" not in out and "Desai" not in out and "700016" not in out


def test_amounts_dates_and_identifiers_are_left_alone():
    text = ("The surveyor estimated INR 178500 and INR 1,500,000 IDV. Claim CLM-2026-00418, "
            "date of loss 2026-03-31, under Policy PW-MOTOR-001 clause 3. Claim amount "
            "560038 rupees was disputed.")
    assert redact.scrub_claimant(text) == text


def test_claim_and_policy_numbers_survive_when_claim_ids_false():
    text = "claim CLM-2026-00418 under Policy PW-MOTOR-001"
    assert redact.scrub(text, claim_ids=False) == text
    assert "CLM-2026-00418" not in redact.scrub(text)          # default is unchanged


def test_idempotent():
    once = redact.scrub_claimant(FNOL_1)
    assert redact.scrub_claimant(once) == once


def test_none_and_empty_are_safe():
    assert redact.scrub_claimant(None) is None
    assert redact.scrub_claimant("") == ""


def test_bare_word_injury_is_not_redacted():
    # "injury" alone is policy vocabulary ("bodily injury"); only specific injuries are PII.
    text = "Bodily injury to a third party is outside the Own Damage section."
    assert redact.scrub_claimant(text) == text


def test_scrub_deep_passes_the_claim_ids_switch_through():
    row = {"claim": "CLM-2026-00418", "nested": ["POL-TN-99231"]}
    assert redact.scrub_deep(row, claim_ids=False) == row
    assert redact.scrub_deep(row) != row


# ---- SEAMS.md S14: the address/PIN patterns corrupted identifiers and amounts in the trace logs
def test_hex_trace_ids_and_referral_ids_survive_the_claimant_scrubber():
    text = "trace cap_cf442790a57f and cap_1ba740483b7f, referral REF-9F623718"
    assert redact.scrub_claimant(text) == text


def test_six_digit_amounts_are_not_read_as_pin_codes():
    text = '{"policy_limit":{"amount":600000.0,"type":"IDV"},"note":"IDV INR 600000"}'
    assert redact.scrub_claimant(text) == text


def test_the_verb_address_is_not_an_address_cue():
    text = "The adjuster should address the question. Facts are addressed in clause 2."
    assert redact.scrub_claimant(text) == text


def test_a_pin_after_a_place_name_is_still_redacted():
    assert "560038" not in redact.scrub_claimant("Posted to Bengaluru 560038, per file.")


def test_structural_keys_bypass_the_scrubber_at_any_depth():
    row = {"trace_id": "cap_cf442790a57f", "spans": [{"referral_id": "REF-9F623718",
           "note": "Ravi Kumar Sharma lives at 14 MG Road, Indiranagar"}]}
    out = redact.scrub_claimant_deep(row, frozenset({"trace_id", "referral_id"}))
    assert out["trace_id"] == "cap_cf442790a57f"
    assert out["spans"][0]["referral_id"] == "REF-9F623718"
    assert "Indiranagar" not in out["spans"][0]["note"]
