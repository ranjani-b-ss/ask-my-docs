"""The claim files the agent and the workflow triage — motor own-damage claims only.

Restricted to one line of business on purpose. ``compute_payout`` takes a flat deductible
amount; health claims in this corpus use a percentage co-payment instead, which is a
different arithmetic shape and would force the tool to branch on line-of-business, breaking
"one job" (requirement 1 of the Week 7 brief). Ten motor claims is enough to force every
dependency the brief asks for without that complication.

Every fact below — the deductible amounts, the exclusion wording, the endorsement dates — is
checked against ``corpora/insurance/policy-wording/01-motor-own-damage.md`` and
``corpora/insurance/endorsements/END-2026-01-motor.md`` before being written into a claim, the
same discipline Week 6's ``eval/claim_cases.yaml`` used. The gold answers this dataset is
graded against live separately, in ``eval/race_cases.yaml`` — never here, so a tool call can't
leak the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Claim:
    claim_id: str
    date_of_loss: str          # YYYY-MM-DD
    vehicle_cc: int
    claim_amount: float        # what the claimant submitted, BEFORE any deductions
    notes: str                 # the adjuster's free-text narrative


CLAIMS: dict[str, Claim] = {
    c.claim_id: c
    for c in [
        Claim(
            "C-001", "2026-02-10", 1400, 8000.0,
            "Reversing out of a parking bay, the insured clipped a concrete bollard. Front "
            "bumper dented and scraped. No other vehicle involved, no injuries. Surveyor's "
            "repair estimate: INR 8,000. Nothing else noted.",
        ),
        Claim(
            "C-002", "2026-06-01", 1800, 15000.0,
            "Side-swiped by another vehicle changing lanes on the highway. Rear-left door "
            "and panel damaged. Other driver's insurer has accepted liability separately; "
            "this is the own-damage claim on our policy. Surveyor's estimate: INR 15,000.",
        ),
        Claim(
            "C-003", "2026-05-01", 1400, 6400.0,
            "Insured drove through a deep pothole on a flooded street. Both nearside tyres "
            "burst and had to be replaced. Surveyor confirms no other part of the vehicle "
            "was damaged — the body, suspension and wheel rims are all intact. Two tyres "
            "replaced at INR 3,200 each.",
        ),
        Claim(
            "C-004", "2026-03-22", 1200, 22000.0,
            "Single-vehicle accident, insured's car went off the road on a bend and struck a "
            "guardrail. Front-end damage. Police report on file: the person driving at the "
            "time was the insured's nephew, who does not hold a valid driving licence. "
            "Insured was not in the vehicle. Repair estimate: INR 22,000.",
        ),
        Claim(
            "C-005", "2026-04-18", 1500, 19000.0,
            "Insured lost control on a roundabout at night and struck a lamp post. Front "
            "and side damage. Police attended the scene and administered a breathalyzer; "
            "the report confirms the insured's blood alcohol reading was above the legal "
            "limit at the time of the accident. Repair estimate: INR 19,000.",
        ),
        Claim(
            "C-006", "2026-07-09", 1300, 27000.0,
            "Rear-end collision at a signal. On reviewing the claim file, the investigator "
            "found the insured had been logged into a ride-hailing driver app and had "
            "completed two paid airport pickups earlier that day in this private car — it "
            "was being used commercially for hire at the time, which is outside the use "
            "declared on the schedule. Repair estimate: INR 27,000.",
        ),
        Claim(
            "C-007", "2026-03-01", 1400, 40000.0,
            "Rear-ended while stationary at traffic lights; not at fault. Surveyor's repair "
            "estimate is INR 34,000. The claimant has also submitted a separate bill for "
            "INR 6,000 for a hire car used for 5 days while the vehicle was in the "
            "workshop, and is claiming the full INR 40,000 as one figure. Vehicle is "
            "1400cc.",
        ),
        Claim(
            "C-008", "2026-01-20", 1350, 5000.0,
            "A stone thrown up by a passing truck on the motorway cracked the windscreen. "
            "No other damage. Glass replaced at a specialist. Surveyor's invoice: INR "
            "5,000.",
        ),
        Claim(
            "C-009", "2026-06-20", 1600, 65000.0,
            "The gearbox seized while the insured was driving normally on the highway; the "
            "AA breakdown report attached to the file states 'internal transmission "
            "failure, no evidence of external impact or collision'. No other vehicle or "
            "object was involved. Recovery and workshop estimate: INR 65,000.",
        ),
        Claim(
            "C-010", "2026-05-15", 1500, 180000.0,
            "Insured drove into a flooded underpass despite a police barricade diverting "
            "traffic around it; the engine subsequently hydrolocked and the vehicle had to "
            "be towed. Surveyor's report notes the water level and the barricade, but is "
            "explicit that it 'cannot determine from the physical evidence alone whether "
            "the damage should be classified as flood damage or as a mechanical failure "
            "resulting from the insured continuing to drive through standing water against "
            "a warning'. Repair estimate: INR 180,000.",
        ),
    ]
}


def get(claim_id: str) -> Claim:
    if claim_id not in CLAIMS:
        raise KeyError(f"No such claim: {claim_id!r}. Known ids: {sorted(CLAIMS)}")
    return CLAIMS[claim_id]


def all_claim_ids() -> list[str]:
    return sorted(CLAIMS)
