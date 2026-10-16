#!/usr/bin/env python
"""Week 12 — the MCP server this project OWNS: policy-wording search, scoped by product and date.

    ./.venv/bin/python src/mcp_servers/wording_server.py

Any MCP client can call ``search_wording``. The scoping is enforced here, in code, not asked for in
a prompt: wording that was not in force on the loss date, or that belongs to another product, is
removed before the caller ever sees it (``src/retriever.py::in_force_hits``).

What this server hands to another squad's agent: policy wording chunks and their ids / versions /
effective dates. It never touches a claim file, so there is no claimant PII on this path — and
the span it writes keeps chunk ids, not text. The calling agent's own query text is redacted
before it is logged, in case a model copied claimant words into it.

No LLM runs here (see src/agent/triage_agent.py for the one place that does).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastmcp import FastMCP

from src import span_log, wording_versions
from src.config import CANDIDATE_K, capstone_chunking
from src.retriever import retrieve

mcp = FastMCP(name="policy-wording")
CORPUS = "insurance"
PRODUCTS = ("motor", "health")


def date_filter_enabled() -> bool:
    """On unless WORDING_DATE_FILTER=off. The switch exists for the loss-date ablation (eval/run_straddle_ablation.py)
    and nothing else: with it off, search_wording returns the best wording of ANY date, as retrieval did before Week 12."""
    return os.environ.get("WORDING_DATE_FILTER", "on").lower() != "off"


@mcp.tool
def search_wording(query: str, product: str, loss_date: str, top_k: int = 3,
                   trace_id: str = "") -> dict:
    """Search the policy wording and endorsements IN FORCE on a loss date, for one product.

    Always pass the claim's date of loss as `loss_date` (YYYY-MM-DD) and the product
    (`motor` or `health`). Wording that took effect AFTER the loss date, and wording that
    belongs to the other product, is removed for you — so every clause returned is one a
    decision on this loss may rely on. Each hit carries its document id, version, effective
    date, clause heading and chunk id: cite all of them, never just "the policy". A hit whose
    `superseded_by` is set is a clause that endorsement amended before this loss: its figures are
    no longer the ones in force, so cite the endorsement's clause and do not cite the amended one.

    Exclusions rarely use the claim's own words, so a query built only from the claim's facts can
    miss them: to check for exclusions, search for the section titled "What is not covered" and
    read its whole list. Does not read claim files and does not decide anything — it returns
    wording, nothing else. If `hits` is empty, no wording for
    this product was in force on that date: say so, do not retry the same search.
    """
    if product not in PRODUCTS:
        raise ValueError(f"product must be one of {list(PRODUCTS)}, got {product!r}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", loss_date or ""):
        raise ValueError(f"loss_date must look like YYYY-MM-DD (for example 2026-03-31), got {loss_date!r}")
    top_k = max(1, min(int(top_k), 8))

    def _search() -> dict:
        scoped = date_filter_enabled()
        cfg = capstone_chunking()
        r = retrieve(query, cfg=cfg, corpus_id=CORPUS, top_k=top_k,
                     candidate_k=CANDIDATE_K, min_cosine=0.0, min_rerank_score=0.0,
                     loss_date=loss_date if scoped else None, product=product if scoped else None)
        amends = wording_versions.load_amendments(CORPUS, cfg.slug)
        hits = [{
            "superseded_by": wording_versions.superseded_by(
                amends, h.meta.get("document_id"), h.meta.get("section") or "", loss_date),
            "chunk_id": h.chunk_id,
            "document_id": h.meta.get("document_id"),
            "version": h.meta.get("version"),
            "effective_date": h.meta.get("effective_date"),
            "clause": h.meta.get("section") or "",
            "relevance": h.rerank_score if h.rerank_score is not None else h.cosine,
            "text": h.text,
        } for h in r.hits]
        return {"product": product, "resolved_against": loss_date, "index": cfg.slug, "hits": hits,
                "dropped_not_in_force": r.diagnostics.get("dropped_not_in_force", 0)}

    return span_log.run_logged(
        "policy-wording", "search_wording", trace_id,
        {"query": query, "product": product, "loss_date": loss_date, "top_k": top_k},
        _search,
        lambda res: {"chunk_ids": [h["chunk_id"] for h in res["hits"]],
                     "dropped_not_in_force": res["dropped_not_in_force"]},
    )


if __name__ == "__main__":
    mcp.run()
