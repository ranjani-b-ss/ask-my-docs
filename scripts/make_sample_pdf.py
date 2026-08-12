"""Generates the one PDF in the placeholder corpus, so the PDF loader is exercised.

Run once: python scripts/make_sample_pdf.py

When the assigned document pack arrives this script becomes unnecessary — it exists only
so the placeholder corpus contains a real multi-page PDF rather than Markdown alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

OUT = (
    Path(__file__).resolve().parent.parent
    / "corpora" / "insurance" / "policy-wording" / "04-definitions.pdf"
)

BLOCKS: list[tuple[str, str]] = [
    ("h1", "Standard Definitions and Interpretation"),
    ("p", "Meridian Assurance Limited &mdash; Document PW-DEFS-004, version 1.8, effective "
          "1 April 2025. Applies to all lines of business."),
    ("note", "PLACEHOLDER CORPUS. Meridian Assurance Limited is a fictional insurer. This "
             "document was written for a RAG training exercise and states no real policy "
             "terms."),

    ("h2", "1. Interpretation"),
    ("p", "Words in the singular include the plural and vice versa. A reference to a clause "
          "is a reference to a clause of the policy wording in which the reference appears. "
          "Headings are for convenience and do not affect construction. Where a term is "
          "defined in both this document and a line-specific policy wording, the "
          "line-specific definition prevails for that line of business."),

    ("h2", "2. Definitions"),
    ("p", "<b>Accident</b> means a sudden, unforeseen, and involuntary event caused by "
          "external, visible, and violent means."),
    ("p", "<b>Cashless facility</b> means a facility under which the Company pays the cost "
          "of admissible treatment directly to a network provider, to the extent "
          "pre-authorisation has been granted."),
    ("p", "<b>Condition precedent</b> means a policy term on which the Company's liability "
          "under the policy is conditional."),
    ("p", "<b>Co-payment</b> means a cost-sharing requirement under which the Insured Person "
          "bears a specified percentage of the admissible claim amount. A co-payment does "
          "not reduce the sum insured."),
    ("p", "<b>Deductible</b> means a cost-sharing requirement under which the Company is "
          "not liable for a specified amount, which applies before any liability of the "
          "Company arises. A deductible does not reduce the sum insured."),
    ("p", "<b>Grace period</b> means the period of <b>30 days</b> immediately following the "
          "premium due date during which premium may be paid to continue the policy without "
          "loss of continuity benefits. Coverage is not available for the period for which "
          "no premium was received."),
    ("p", "<b>Insured Declared Value (IDV)</b> means the sum arrived at by applying the "
          "depreciation schedule for the age of the vehicle to the manufacturer&rsquo;s "
          "listed selling price of the vehicle, and is the maximum sum payable in the event "
          "of a total loss."),

    ("pagebreak", ""),

    ("p", "<b>Material fact</b> means a fact that would influence the judgement of a prudent "
          "underwriter in deciding whether to accept a risk and on what terms. The Insured "
          "has a continuing duty to disclose material facts."),
    ("p", "<b>Network provider</b> means a hospital, garage, or other provider that has "
          "entered into an agreement with the Company or its administrator to provide "
          "services on a cashless basis at agreed rates."),
    ("p", "<b>Pre-existing disease</b> means any condition, ailment, injury, or disease that "
          "is diagnosed by a physician <b>within 36 months</b> before the effective date of "
          "the policy, or for which medical advice or treatment was recommended by or "
          "received from a physician within 36 months before the effective date."),
    ("p", "<b>Reasonable and customary charges</b> means charges for services or supplies "
          "that are the standard charges for the geographic area where provided, and no more "
          "than the charges would have been had no insurance existed."),
    ("p", "<b>Sum insured</b> means the maximum amount of the Company&rsquo;s liability, as "
          "stated in the schedule, for each Insured Person or for the policy as a whole "
          "where the schedule states the cover is on a floater basis."),
    ("p", "<b>Surveyor</b> means a person licensed to assess and report on the cause and "
          "quantum of a loss. The surveyor&rsquo;s report is advisory; the decision on the "
          "claim rests with the Company."),
    ("p", "<b>Third-party administrator</b> means a person engaged by the Company to provide "
          "claim-related services, including pre-authorisation and document verification. "
          "The administrator does not decide admissibility."),
    ("p", "<b>Total loss</b> means loss of the insured property where it is destroyed, or "
          "stolen and not recovered, or where the cost of retrieval and repair exceeds the "
          "threshold stated in the applicable policy wording."),

    ("h2", "3. Free look period"),
    ("p", "Where a policy is issued for a term of one year or more, the Insured may review "
          "the terms and, if not acceptable, return the policy within <b>15 days</b> of "
          "receipt, or within <b>30 days</b> where the policy was sold through distance "
          "marketing. Premium is refunded after deducting proportionate risk premium for the "
          "period of cover and expenses on medical examination and stamp duty."),

    ("h2", "4. Cancellation"),
    ("p", "The Insured may cancel at any time on <b>7 days</b> written notice, and premium is "
          "refunded on a short-period scale. The Company may cancel only on grounds of "
          "established fraud, misrepresentation, or non-cooperation, on <b>15 days</b> "
          "written notice, and no refund is payable where cancellation is for established "
          "fraud."),

    ("h2", "5. Renewal and portability"),
    ("p", "A policy is ordinarily renewable for life, subject to payment of premium and the "
          "absence of established fraud. An Insured Person may port to another insurer by "
          "applying <b>at least 45 days but not more than 60 days</b> before the renewal "
          "date, and accrued continuity benefits in respect of waiting periods are carried "
          "forward to the extent of the sum insured under the previous policy."),
]


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10.5, leading=15.5,
                          spaceAfter=7, alignment=TA_LEFT)
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=17, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12.5, spaceBefore=12,
                        spaceAfter=6)
    note = ParagraphStyle("note", parent=body, fontSize=8.5, leading=11,
                          textColor="#666666", spaceAfter=12)

    style_map = {"h1": h1, "h2": h2, "p": body, "note": note}
    flow = []
    for kind, text in BLOCKS:
        if kind == "pagebreak":
            flow.append(PageBreak())
            continue
        flow.append(Paragraph(text, style_map[kind]))
    flow.append(Spacer(1, 6 * mm))

    SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        title="Standard Definitions and Interpretation",
        author="Meridian Assurance Limited",
        subject="PW-DEFS-004 v1.8 effective 2025-04-01",
    ).build(flow)
    print(f"wrote {OUT}  ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build()
    sys.exit(0)
