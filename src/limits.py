"""Week 12 — the three numbers, kept distinct: deductible, sub-limit, policy limit.

Juniors confuse these weekly, and a model asked to "report the deductible" from two retrieved
passages picked the wrong one four times out of four in Week 10. So which row of the
effective-dated table governs is a date comparison done HERE, in code, and the model is only
ever handed the result. Each number carries the document, version and clause it came from and
the loss date it was resolved against — that is what makes it citable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

TABLE_PATH = Path(__file__).resolve().parent.parent / "registry" / "limits_table.yaml"


@lru_cache(maxsize=1)
def _table() -> dict:
    return yaml.safe_load(TABLE_PATH.read_text(encoding="utf-8"))


def _governing(rows: list[dict], loss_date: str) -> dict | None:
    """The row with the latest ``effective_from`` that is on or before the loss date."""
    in_force = [r for r in rows if r["effective_from"] <= loss_date]
    return max(in_force, key=lambda r: r["effective_from"]) if in_force else None


def _cite(row: dict, loss_date: str) -> dict:
    return {**row["source"], "effective_date": row["effective_from"], "resolved_against": loss_date}


def get_limits(product: str, loss_date: str, vehicle_cc: int | None = None,
               insured_age: int | None = None, policy: dict | None = None) -> dict:
    """Deductible, co-payment, sub-limits and policy limit for one loss, resolved to the
    wording in force on ``loss_date``. ``policy`` is the registry record (for the third
    number — the policy limit — which belongs to the individual policy, not the wording)."""
    table = _table().get(product)
    if table is None:
        raise ValueError(f"unknown product {product!r}; known: {sorted(_table())}")

    out: dict = {"product": product, "loss_date": loss_date}

    # 1) deductible (motor) — or an explicit "not applicable" (health)
    if table.get("deductible"):
        row = _governing(table["deductible"], loss_date)
        if row is None:
            out["deductible"] = {"applies": False, "reason": "no deductible wording was in force on the loss date"}
        elif vehicle_cc is None:
            out["deductible"] = {"applies": True, "amount": None, "currency": "INR",
                                 "needs": "vehicle_cc", "tiers": row["tiers"], **_cite(row, loss_date)}
        else:
            tier = next(t for t in row["tiers"] if t["max_cc"] is None or vehicle_cc <= t["max_cc"])
            out["deductible"] = {"applies": True, "amount": tier["amount"], "currency": "INR",
                                 "vehicle_cc": vehicle_cc, **_cite(row, loss_date)}
    else:
        out["deductible"] = {"applies": False,
                             "reason": f"{product} policies in this corpus use a co-payment, not a deductible"}

    # 2) co-payment (health)
    if table.get("co_payment"):
        row = _governing(table["co_payment"], loss_date)
        if row is None:
            out["co_payment"] = {"applies": False, "reason": "no co-payment wording was in force on the loss date"}
        elif insured_age is None:
            out["co_payment"] = {"applies": None, "needs": "insured_age", "percent": row["percent"],
                                 "applies_from_age": row["applies_from_age"], **_cite(row, loss_date)}
        else:
            applies = insured_age >= row["applies_from_age"]
            out["co_payment"] = {"applies": applies, "percent": row["percent"] if applies else None,
                                 "applies_from_age": row["applies_from_age"],
                                 "insured_age": insured_age, **_cite(row, loss_date)}

    # 3) sub-limits — resolved per name so a later row replaces the earlier one of the same name
    sub_limits = []
    for name in dict.fromkeys(r["name"] for r in table.get("sub_limits", [])):
        row = _governing([r for r in table["sub_limits"] if r["name"] == name], loss_date)
        if row is None:
            continue
        entry = {"name": name, "kind": row["kind"], "value": row["value"], **_cite(row, loss_date)}
        if "proportionate_deduction" in row:
            entry["proportionate_deduction"] = row["proportionate_deduction"]
        if row["kind"] == "percent_of_sum_insured_per_day" and policy and policy.get("policy_limit"):
            si = policy["policy_limit"]["amount"]
            entry["amount_per_day"] = round(si * row["value"] / 100)
            entry["of_sum_insured"] = si
        sub_limits.append(entry)
    out["sub_limits"] = sub_limits

    # 4) the policy limit — a property of the individual policy, never of the wording
    if policy and policy.get("policy_limit"):
        out["policy_limit"] = {**policy["policy_limit"], "policy_number": policy["policy_number"],
                               "source": "policy registry (synthetic)"}
    else:
        out["policy_limit"] = None
    return out
