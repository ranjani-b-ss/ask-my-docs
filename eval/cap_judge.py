"""Week 12 — LLM judge for the integrated system: is the adjuster-facing PROSE grounded?

Division of labour (same principle as Week 6): the deterministic assertions in src/cap_assertions.py own
everything mechanical — in force, version, grounded chunk ids, three numbers, PII. The judge owns the one
thing left that needs reading: does each statement about the wording in the model's prose (summary,
referral reason, the "why" lines) have support in what the model was actually shown?

What the judge is given, rebuilt from the TRACE ALONE: every chunk retrieved in that run (text fetched from
the index by chunk id, and checked against the content hash the trace stored — a mismatch means the index
changed since the run and the case is refused, not guessed), the claim file with claimant details scrubbed,
and the limits tool's result. What it is asked to grade: summary + referral reason + "why" lines.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPT_DIR = ROOT / "eval"


class ChunkStores:
    """The chunk text for whichever index a trace ran on. A trace records the index its wording server reported (`index`); traces
    written before 2026-10-13 have no such field and ran on the legacy `recursive` index, which is kept precisely so they can still
    be rebuilt and hash-verified."""

    def __init__(self):
        self._by_slug: dict[str, dict] = {}

    def for_run(self, run: dict) -> dict:
        from src import store
        from src.config import LEGACY_CAPSTONE_SLUG, chunking_from_slug
        slug = run.get("index") or LEGACY_CAPSTONE_SLUG
        if slug not in self._by_slug:
            got = store.get_collection(chunking_from_slug(slug), "insurance").get(include=["documents", "metadatas"])
            self._by_slug[slug] = {i: (d, m) for i, d, m in zip(got["ids"], got["documents"], got["metadatas"])}
        return self._by_slug[slug]


def _chunk_store() -> ChunkStores:
    return ChunkStores()


def load_runs(versions=("v1", "v2")) -> dict:
    """{(version, claim): trace row} for the eval runs that completed (same filter as the taxonomy). Default: the 72 v1/v2 runs."""
    runs = {}
    for line in (ROOT / "traces" / "capstone_traces.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        lab = str(r.get("submitted_by", ""))
        if lab in tuple(f"capstone-eval-{v}" for v in versions) and r["usage"]["total_tokens"] > 0 \
                and "max_wall" not in str(r["stop_reason"]):
            runs[(lab.removeprefix("capstone-eval-"), r["claim_number"])] = r
    return runs


def build_case(run: dict, chunks: dict) -> dict:
    """Everything the judge sees for one run. Raises if the stored context hash no longer matches."""
    from src import claim_files, redact
    p, claim = run["packet"], claim_files.get(run["claim_number"])
    passages, mismatched = [], []
    chunks = chunks.for_run(run)
    for cid, stored_sha in (run.get("retrieved_context") or {}).items():
        text, meta = chunks[cid]
        if hashlib.sha256(text.encode()).hexdigest()[:12] != stored_sha:
            mismatched.append(cid)
        passages.append({"n": len(passages) + 1, "chunk_id": cid, "document_id": meta["document_id"],
                         "version": meta.get("version"), "effective_date": meta.get("effective_date"),
                         "section": meta.get("section") or "", "text": text})
    if mismatched:
        raise ValueError(f"index no longer matches the trace for {mismatched}")
    prose = {"summary": p["summary_for_adjuster"], "referral_reason": str(p["referral"].get("reason") or ""),
             "why": [w.get("why", "") for w in p["wording"] if w.get("why")]}
    return {"claim_number": run["claim_number"], "trace_id": run["trace_id"], "loss_date": claim.loss_date,
            "claim_file": (f"Product: {claim.product}. Date of loss: {claim.loss_date}. "
                           f"Narrative (identifying details removed): {redact.scrub_claimant(claim.narrative)} "
                           f"Adjuster's question: {redact.scrub_claimant(claim.coverage_question)}"),
            "in_force": (p["in_force"] or {}).get("reason", ""),
            "numbers": p.get("numbers"), "passages": passages, "prose": prose}


def render_passages(case: dict) -> str:
    out = []
    for q in case["passages"]:
        out.append(f"[{q['n']}] document {q['document_id']} v{q['version']}, effective_date {q['effective_date']}, "
                   f"section: {q['section']}\n{q['text'].strip()}")
    return "\n\n".join(out) or "(no passages were retrieved)"


def render_tool_results(case: dict) -> str:
    n = case["numbers"] or {}
    lines = [f"check_in_force: {case['in_force']}"]
    d = n.get("deductible") or {}
    if d:
        lines.append(f"get_limits deductible: {json.dumps(d)}")
    if n.get("co_payment"):
        lines.append(f"get_limits co_payment: {json.dumps(n['co_payment'])}")
    for s in n.get("sub_limits", []):
        lines.append(f"get_limits sub_limit: {json.dumps(s)}")
    if n.get("policy_limit"):
        lines.append(f"get_limits policy_limit: {json.dumps(n['policy_limit'])}")
    return "\n".join(lines)


def render_prose(case: dict) -> str:
    pr = case["prose"]
    parts = [f"Summary: {pr['summary']}", f"Referral reason: {pr['referral_reason']}"]
    parts += [f"Why line {i + 1}: {w}" for i, w in enumerate(pr["why"])]
    return "\n".join(parts)


def load_prompt(version: str) -> tuple[str, str]:
    raw = (PROMPT_DIR / f"judge_cap_{version}.txt").read_text(encoding="utf-8")
    body = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("#")).strip()
    return body, hashlib.sha256(body.encode()).hexdigest()[:12]
