"""Week 12 — which base-policy clauses an in-force endorsement has amended (SEAMS.md S12).

The loss-date filter removes wording that was not yet in force. It cannot remove wording that
WAS in force but has since been amended: the base clause and the endorsement clause both pass,
and a packet citing both puts two different figures in front of the adjuster. This builds the
clause-level map from the index's own chunk headings ("Amendment to Clause 2.2") so the
retrieval hop can mark the amended clause instead of trusting the model to notice.
"""

from __future__ import annotations

import re
from functools import lru_cache

_AMENDS = re.compile(r"(?i)\bamendment to clause\s+(\d+(?:\.\d+)?[A-Z]?)")
_CLAUSE = re.compile(r"(\d+(?:\.\d+)?[A-Z]?)\b")


def clause_number(clause_path: str) -> str | None:
    """'... > 2. Basis of settlement > 2.2 Compulsory deductible' -> '2.2'."""
    last = (clause_path or "").split(">")[-1].strip()
    m = _CLAUSE.match(last)
    return m.group(1) if m else None


def amendment_map(metadatas: list[dict]) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """(base document_id, clause number) -> [(endorsement id, its effective_date)]."""
    out: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for meta in metadatas:
        base, doc = meta.get("supersedes"), meta.get("document_id")
        found = _AMENDS.search(str(meta.get("section") or ""))
        if not (base and doc and found):
            continue
        entry = (str(doc), str(meta.get("effective_date") or ""))
        bucket = out.setdefault((str(base), found.group(1)), [])
        if entry not in bucket:
            bucket.append(entry)
    return out


def superseded_by(amendments: dict, document_id: str, clause_path: str,
                  loss_date: str) -> str | None:
    """The endorsement, in force on ``loss_date``, that amended this clause — else None.
    An endorsement dated after the loss amends nothing for this claim."""
    num = clause_number(clause_path)
    if not num:
        return None
    for end_id, eff in amendments.get((document_id, num), []):
        if eff and eff <= loss_date:
            return end_id
    return None


@lru_cache(maxsize=8)
def load_amendments(corpus_id: str, slug: str | None = None) -> dict:
    from . import store
    from .config import capstone_chunking, chunking_from_slug
    collection = store.get_collection(chunking_from_slug(slug) if slug else capstone_chunking(), corpus_id)
    return amendment_map(collection.get(include=["metadatas"])["metadatas"] or [])
