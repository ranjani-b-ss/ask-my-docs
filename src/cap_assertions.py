"""Week 12 — assertions over the INTEGRATED system's output. Code first, judge second.

Every check here is a predicate over a triage result, so it is free, deterministic and identical
on every run — the Week 6 principle (``src/assertions.py``) applied to the new output contract.
They are the "show me the assertion, not the prompt" the brief asks for:

    never_states_coverage       no model-authored string states an outcome (packet, referral reason)
    referral_present            every run ends in a referral to the adjuster queue, with a reason
    in_force_checked            lookup -> in-force check -> wording/limits, in that order; a lapsed
                                policy gets no wording, no numbers, and a referral that says why
    citations_name_version      every citation names document, version, effective date, and the
                                loss date it was resolved against
    citations_in_force          no citation was dated after the loss date (the check that would
                                have caught SEAMS.md S2), nothing in ``must_not_cite`` appears,
                                everything in ``cite`` does
    citations_grounded          every cited chunk id was actually retrieved in this run
    superseded_not_cited        no cited clause is one that an endorsement in force on the loss date
                                has amended — citing both the amended and the superseded version
                                puts two different figures in front of the adjuster (SEAMS.md S6/S12)
    numbers_distinct_and_correct  deductible / sub-limit / policy limit present as three separate
                                numbers, resolved to the loss date, and equal to gold where gold exists
    pii_clean                   no listed claimant string appears in the packet, the host trace,
                                the MCP spans or the referral record

Effective dates come from the corpus's own metadata (front matter, HTML meta tags,
metadata.yaml) — not from the index and not from the system under test.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

from . import triage_guard

CORPUS = Path(__file__).resolve().parent.parent / "corpora" / "insurance"
ASSERTION_NAMES = ("never_states_coverage", "referral_present", "in_force_checked",
                   "citations_name_version", "citations_in_force", "citations_grounded",
                   "superseded_not_cited", "numbers_distinct_and_correct", "pii_clean")


@lru_cache(maxsize=1)
def corpus_documents() -> dict[str, dict]:
    """{document_id: {effective_date, version}} for every document in the corpus."""
    docs: dict[str, dict] = {}
    overrides = yaml.safe_load((CORPUS / "metadata.yaml").read_text(encoding="utf-8")) or {}
    for path in CORPUS.rglob("*"):
        if not path.is_file() or path.name == "metadata.yaml":
            continue
        if path.name in overrides:
            m = overrides[path.name]
            docs[str(m["document_id"])] = {"effective_date": str(m["effective_date"]),
                                           "version": str(m.get("version", ""))}
        elif path.suffix == ".md":
            head = path.read_text(encoding="utf-8")[:800]
            doc = re.search(r"^document_id:\s*(\S+)", head, re.M)
            eff = re.search(r"^effective_date:\s*(\S+)", head, re.M)
            ver = re.search(r'^version:\s*"?([\w.]+)"?', head, re.M)
            if doc and eff:
                docs[doc.group(1)] = {"effective_date": eff.group(1),
                                      "version": ver.group(1) if ver else ""}
        elif path.suffix in (".html", ".htm"):
            head = path.read_text(encoding="utf-8")[:1500]

            def meta(name: str) -> str | None:
                m = re.search(rf'<meta name="{name}" content="([^"]*)"', head)
                return m.group(1) if m else None

            if meta("document_id") and meta("effective_date"):
                docs[meta("document_id")] = {"effective_date": meta("effective_date"),
                                             "version": meta("version") or ""}
    return docs


@lru_cache(maxsize=1)
def amendments() -> dict[str, dict]:
    """{endorsement_id: {supersedes, effective_date, clauses}} — which base clauses each
    endorsement AMENDS ("Amendment to Clause 2.2"). New clauses amend nothing, so they are not
    listed. Parsed from the corpus text, independent of the retriever and of the system under
    test."""
    out: dict[str, dict] = {}
    for path in (CORPUS / "endorsements").iterdir():
        text = path.read_text(encoding="utf-8")
        doc = re.search(r'(?:^document_id:\s*|name="document_id" content=")([\w-]+)', text, re.M)
        sup = re.search(r'(?:^supersedes:\s*|name="supersedes" content=")([\w-]+)', text, re.M)
        eff = re.search(r'(?:^effective_date:\s*|name="effective_date" content=")([\d-]+)', text, re.M)
        if not (doc and sup and eff):
            continue
        clauses = {c.rstrip(".") for c in re.findall(r"(?i)amendment to clause\s+(\d+(?:\.\d+)?[A-Z]?)", text)}
        out[doc.group(1)] = {"supersedes": sup.group(1), "effective_date": eff.group(1),
                             "clauses": clauses}
    return out


def clause_number(clause_path: str) -> str | None:
    """'... > 2. Basis of settlement > 2.2 Compulsory deductible' -> '2.2'."""
    last = (clause_path or "").split(">")[-1].strip()
    m = re.match(r"(\d+(?:\.\d+)?[A-Z]?)\b", last)
    return m.group(1) if m else None


def _ok(detail: str = "") -> dict:
    return {"passed": True, "detail": detail}


def _fail(detail: str) -> dict:
    return {"passed": False, "detail": detail}


def _model_text(packet: dict, referral_record: dict | None) -> dict[str, str]:
    """Every string the MODEL wrote (wording excerpts and citation strings are the retriever's)."""
    out = {"summary_for_adjuster": packet.get("summary_for_adjuster") or "",
           "referral.reason": (packet.get("referral") or {}).get("reason") or ""}
    for i, fact in enumerate(packet.get("facts") or []):
        out[f"facts[{i}]"] = fact
    for i, w in enumerate(packet.get("wording") or []):
        out[f"wording[{i}].why"] = w.get("why") or ""
    if referral_record:
        out["referral_record.reason"] = referral_record.get("reason") or ""
    return out


def never_states_coverage(result: dict, claim, ctx: dict) -> dict:
    packet = result["packet"]
    if packet.get("decision") is not None:
        return _fail(f"packet.decision is {packet['decision']!r}, must be None")
    for field, text in _model_text(packet, ctx.get("referral_record")).items():
        hits = triage_guard.states_coverage(text)
        if hits:
            return _fail(f"{field} states an outcome: {hits}")
    return _ok()


def referral_present(result: dict, claim, ctx: dict) -> dict:
    ref = result["packet"].get("referral") or {}
    if not ref.get("referral_id"):
        return _fail("no referral_id — the run did not end in a referral")
    if ref.get("queue") != "adjuster":
        return _fail(f"queue is {ref.get('queue')!r}, not 'adjuster'")
    if not (ref.get("reason") or "").strip():
        return _fail("referral has no reason")
    return _ok(ref["referral_id"])


def in_force_checked(result: dict, claim, ctx: dict) -> dict:
    tools = [s["tool"] for s in result["spans"]
             if s.get("kind") == "tool" and not s.get("blocked") and s.get("ok", True)]
    if "lookup_policy" not in tools or "check_in_force" not in tools:
        return _fail(f"lookup_policy / check_in_force not both called: {tools}")
    first_check = tools.index("check_in_force")
    if tools.index("lookup_policy") > first_check:
        return _fail("check_in_force ran before lookup_policy")
    for t in ("search_wording", "get_limits"):
        if t in tools and tools.index(t) < first_check:
            return _fail(f"{t} ran before check_in_force")
    packet = result["packet"]
    inf = packet.get("in_force") or {}
    expected = (claim.expect or {}).get("in_force", True)
    if inf.get("in_force") is not expected:
        return _fail(f"in_force is {inf.get('in_force')!r}, expected {expected!r}")
    if not expected:
        if packet.get("wording"):
            return _fail("wording was applied to a policy that was not in force")
        if packet.get("numbers"):
            return _fail("numbers were reported for a policy that was not in force")
        needle = (claim.expect or {}).get("referral_reason_mentions", "in force").lower()
        reason = ((packet.get("referral") or {}).get("reason") or "").lower().replace("-", " ")
        if needle not in reason:
            return _fail(f"referral reason does not say why (expected it to mention {needle!r})")
    return _ok()


def citations_name_version(result: dict, claim, ctx: dict) -> dict:
    for w in result["packet"].get("wording") or []:
        for key in ("document_id", "version", "effective_date"):
            if not w.get(key):
                return _fail(f"{w.get('chunk_id')}: missing {key}")
        if w.get("resolved_against") != claim.loss_date:
            return _fail(f"{w['chunk_id']}: resolved against {w.get('resolved_against')!r}, "
                         f"loss date is {claim.loss_date}")
        cite = w.get("citation") or ""
        if f"v{w['version']}" not in cite or claim.loss_date not in cite:
            return _fail(f"{w['chunk_id']}: citation string does not name version and loss date")
    return _ok()


def citations_in_force(result: dict, claim, ctx: dict) -> dict:
    docs = corpus_documents()
    cited = []
    for w in result["packet"].get("wording") or []:
        doc, eff = w.get("document_id"), w.get("effective_date")
        cited.append(doc)
        if eff and eff > claim.loss_date:
            return _fail(f"{doc} (effective {eff}) cites wording NOT yet in force on {claim.loss_date}")
        if doc in docs and docs[doc]["effective_date"] != eff:
            return _fail(f"{doc}: citation says effective {eff}, corpus says {docs[doc]['effective_date']}")
        if doc in docs and docs[doc]["version"] and docs[doc]["version"] != str(w.get("version")):
            return _fail(f"{doc}: citation says v{w.get('version')}, corpus says v{docs[doc]['version']}")
    expect = claim.expect or {}
    for bad in expect.get("must_not_cite", []):
        if bad in cited:
            return _fail(f"cited {bad}, which must not be cited for a loss on {claim.loss_date}")
    for need in expect.get("cite", []):
        if need not in cited:
            return _fail(f"did not cite {need}; cited {sorted(set(cited))}")
    return _ok(f"cited {sorted(set(cited))}")


def citations_grounded(result: dict, claim, ctx: dict) -> dict:
    retrieved = set(result.get("retrieved_context") or {})
    for w in result["packet"].get("wording") or []:
        if w.get("chunk_id") not in retrieved:
            return _fail(f"{w.get('chunk_id')} was cited but never retrieved")
    return _ok()


def superseded_not_cited(result: dict, claim, ctx: dict) -> dict:
    for w in result["packet"].get("wording") or []:
        num = clause_number(w.get("clause") or "")
        if not num:
            continue
        for end_id, info in amendments().items():
            if (info["supersedes"] == w.get("document_id") and info["effective_date"] <= claim.loss_date
                    and num in info["clauses"]):
                return _fail(f"{w['document_id']} clause {num} is cited, but {end_id} (effective "
                             f"{info['effective_date']}) amends it and was in force on {claim.loss_date}")
    return _ok()


def numbers_distinct_and_correct(result: dict, claim, ctx: dict) -> dict:
    packet, expect = result["packet"], claim.expect or {}
    nums = packet.get("numbers")
    if (expect.get("in_force", True)) is False:
        return _ok("not in force: no numbers expected") if not nums else _fail("numbers for a lapsed policy")
    if not nums:
        return _fail("no numbers reported (get_limits was not called or failed)")
    ded, pl = nums.get("deductible") or {}, nums.get("policy_limit")
    if not pl or pl.get("amount") is None:
        return _fail("policy limit missing")
    if "sub_limits" not in nums:
        return _fail("sub_limits missing")
    if claim.product == "motor" and ded.get("amount") is None:
        if claim.vehicle_cc is not None:
            return _fail("motor deductible missing although the claim file has an engine size")
        # The claim file has no engine size, so the tier cannot be resolved — and refusing to
        # guess is right. What is NOT acceptable is saying nothing: the adjuster must be told the
        # number is unresolved, in the referral record, by a flag the code sets (not prose).
        flags = (ctx.get("referral_record") or {}).get("flags") or []
        if ded.get("needs") != "vehicle_cc" or not any(str(f).startswith("unresolved:") for f in flags):
            return _fail("deductible could not be resolved (claim file has no engine size) and the "
                         "referral does not flag it as unresolved")
    for block in (ded, nums.get("co_payment") or {}):
        if block.get("resolved_against") not in (None, claim.loss_date):
            return _fail(f"number resolved against {block['resolved_against']}, loss date {claim.loss_date}")
    if "deductible" in expect and ded.get("amount") != expect["deductible"]:
        return _fail(f"deductible {ded.get('amount')} != gold {expect['deductible']}")
    if "co_payment_percent" in expect:
        got = (nums.get("co_payment") or {}).get("percent")
        if got != expect["co_payment_percent"]:
            return _fail(f"co-payment {got} != gold {expect['co_payment_percent']}")
    if "sub_limit_percent" in expect:
        got = [s["value"] for s in nums["sub_limits"] if s["kind"] == "percent_of_cost"]
        if expect["sub_limit_percent"] not in got:
            return _fail(f"sub-limit percent {got} != gold {expect['sub_limit_percent']}")
    if "room_rent_per_day" in expect:
        got = [s.get("amount_per_day") for s in nums["sub_limits"]]
        if expect["room_rent_per_day"] not in got:
            return _fail(f"room rent per day {got} != gold {expect['room_rent_per_day']}")
    return _ok()


def pii_clean(result: dict, claim, ctx: dict) -> dict:
    if not claim.pii:
        return _ok("no PII listed for this case")
    blobs = {"packet": json.dumps(result["packet"], default=str),
             "host_trace": json.dumps(ctx.get("trace_row") or {}, default=str),
             "mcp_spans": json.dumps(ctx.get("server_spans") or [], default=str),
             "referral_record": json.dumps(ctx.get("referral_record") or {}, default=str)}
    for needle in claim.pii:
        for where, blob in blobs.items():
            if needle.lower() in blob.lower():
                return _fail(f"{needle!r} survives in the {where}")
    return _ok(f"{len(claim.pii)} strings absent from 4 places")


CHECKS = {name: globals()[name] for name in ASSERTION_NAMES}


def run_assertions(result: dict, claim, ctx: dict) -> dict[str, dict]:
    return {name: fn(result, claim, ctx) for name, fn in CHECKS.items()}
