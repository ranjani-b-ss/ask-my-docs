"""Week 12 — one claim-file index over the three places claims have lived.

Seam S5 (SEAMS.md): the agent's claims are ``C-0xx`` in ``src/agent/claims_store.py``, the Week 6
claim files are ``CLM-2026-00xxx`` in ``eval/claim_cases.yaml``, and the Week 12 additions are in
``registry/capstone_claims.yaml``. Nothing could look a claim up across all three. This module
does, and changes none of them — the earlier weeks' stores and gold answers stay exactly as
their own evals expect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ClaimFile:
    claim_number: str
    loss_date: str                      # ISO YYYY-MM-DD
    product: str                        # motor | health
    narrative: str                      # the FNOL / adjuster text — may carry claimant PII
    coverage_question: str
    vehicle_cc: int | None = None
    insured_age: int | None = None
    source: str = ""                    # claims_store | week6 | capstone
    expect: dict = field(default_factory=dict)
    pii: tuple = ()


def _kv_lines(notes: str) -> dict[str, str]:
    """Parse the Week 6 'Key: value' claim file (continuation lines are indented)."""
    out: dict[str, str] = {}
    key = None
    for line in notes.splitlines():
        m = re.match(r"^([A-Z][A-Za-z ]+):\s*(.*)$", line)
        if m and not line.startswith(" "):
            key = m.group(1).strip()
            out[key] = m.group(2).strip()
        elif key and line.strip():
            out[key] += " " + line.strip()
    return out


def _from_claims_store() -> list[ClaimFile]:
    from .agent import claims_store

    return [
        ClaimFile(claim_number=c.claim_id, loss_date=c.date_of_loss, product="motor",
                  narrative=c.notes, coverage_question="Triage this claim.",
                  vehicle_cc=c.vehicle_cc, source="claims_store")
        for c in claims_store.CLAIMS.values()
    ]


def _from_week6() -> list[ClaimFile]:
    cases = yaml.safe_load((ROOT / "eval" / "claim_cases.yaml").read_text(encoding="utf-8"))["cases"]
    files = []
    for case in cases:
        kv = _kv_lines(case["notes"])
        body = " ".join(f"{k}: {v}" for k, v in kv.items()
                        if k not in ("CLAIM FILE", "Claim number", "Date of loss", "Line",
                                     "Coverage question"))
        cc = re.search(r"(\d{3,4})\s*cc", case["notes"])
        age = re.search(r"Insured person:\s*(\d{1,3})", case["notes"])
        files.append(ClaimFile(
            claim_number=kv["Claim number"], loss_date=kv["Date of loss"],
            product=kv["Line"].strip().lower(), narrative=body,
            coverage_question=kv.get("Coverage question", "Triage this claim."),
            vehicle_cc=int(cc.group(1)) if cc else None,
            insured_age=int(age.group(1)) if age else None,
            source="week6", expect={"week6_case_id": case["id"], "week6_mode": case["mode"]},
        ))
    return files


def _from_capstone() -> list[ClaimFile]:
    rows = yaml.safe_load((ROOT / "registry" / "capstone_claims.yaml").read_text(encoding="utf-8"))["claims"]
    return [
        ClaimFile(claim_number=r["claim_number"], loss_date=r["loss_date"], product=r["product"],
                  narrative=" ".join(r["narrative"].split()),
                  coverage_question=r["coverage_question"], vehicle_cc=r.get("vehicle_cc"),
                  insured_age=r.get("insured_age"), source="capstone",
                  expect=r.get("expect", {}), pii=tuple(r.get("pii", ())))
        for r in rows
    ]


@lru_cache(maxsize=1)
def load_all() -> dict[str, ClaimFile]:
    index: dict[str, ClaimFile] = {}
    for cf in _from_claims_store() + _from_week6() + _from_capstone():
        if cf.claim_number in index:
            raise ValueError(f"duplicate claim number across sources: {cf.claim_number}")
        index[cf.claim_number] = cf
    return index


def get(claim_number: str) -> ClaimFile:
    index = load_all()
    if claim_number not in index:
        raise KeyError(f"no claim file {claim_number!r}")
    return index[claim_number]
