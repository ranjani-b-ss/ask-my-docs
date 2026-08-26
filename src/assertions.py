"""Week 6 — the checks a rule can do, so the judge never sees them.

Four criteria used to be in the judge prompt (``eval/judge_v0.txt``). All four are here now,
as regexes, and all four were deleted from the prompt (``eval/judge_v1.txt``).

The reason is not only cost. A model asked "is the claim number in CLM-YYYY-NNNNN form?"
gives a *probably* right answer that costs a network call, varies between runs, and cannot be
debugged — and on a bad day it says yes to ``CLM-26-412``. A regex answers the same question
identically every time, for free, and when it is wrong you can see why in one line. The rule
of thumb this week: if you can write the check as a predicate over the text, it is not a
judgement call and it does not belong to a judge.

What stays with the judge is the one criterion no regex can express: whether the coverage
position and the figures actually follow from the retrieved passages. That needs reading
comprehension over two documents, so it stays judged — and being the only judged criterion,
it can be validated against hand labels, which is the whole point of Week 6.

Each assertion returns (passed, detail). ``detail`` explains a failure in terms an adjuster
would recognise, because a bare False in an eval table tells you nothing at 6pm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

# CLM-YYYY-NNNNN exactly: three letters, a four-digit year, five digits. Written strictly so
# that CLM-26-412 and CLM-2026-4127777 both fail, because both are real data-entry errors
# and a summary that echoes a malformed claim number cannot be matched to a claim file.
CLAIM_NUMBER = re.compile(r"\bCLM-(\d{4})-(\d{5})\b")

# A clause identifier: "Clause 3", "Section D", "Clause 4.2", or an IRDAI exclusion code like
# Excl04 / Code-Excl11 as the real policy wording numbers them.
#
# This deliberately does NOT try to match the document id with a regex. The first version did
# — it required `(PW|END)-...` — and it failed every denial drawn from the real uploaded PDF,
# whose document_id is `UNGALUKKAGA-TAMIL_NADU_(INCLUDING_PUDUCHERRY)_POLICY_WORDINGS`. That
# was the assertion being wrong about the corpus, not the summary being wrong, and an
# assertion that fires on a document-naming convention is worse than no assertion.
#
# The document half is checked separately and more strictly: the cited document must be one
# the retriever actually returned for this claim. A regex can only ask "does this look like a
# document id"; comparing against the retrieved set asks "is this a document you actually
# read", which is the question worth asking.
CLAUSE_ID = re.compile(
    r"(?:Clause|Cl\.|Section|Sec\.|Exclusion)\s*[-–]?\s*[A-Z]?\d+(?:\.\d+)*"
    r"|Code[-\s]?Excl\s*\d+"
    r"|\bExcl\s*\d+",
    re.IGNORECASE,
)

# Money as the corpus writes it: INR 3,000 / Rs. 40,000 / INR 2,00,000 (Indian grouping), or
# a bare number, or a percentage-of-sum-insured style limit.
AMOUNT = re.compile(
    r"(?:INR|Rs\.?|₹)\s*\d[\d,]*(?:\.\d+)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s*(?:INR|Rs\.?|rupees)"
    r"|\b\d+(?:\.\d+)?\s*%\s*of\s+the\s+sum\s+insured",
    re.IGNORECASE,
)

NO_DEDUCTIBLE = re.compile(r"^\s*(none|nil|n/?a|not applicable|no deductible)\b",
                           re.IGNORECASE)
NO_EXCLUSION = re.compile(r"^\s*(none|nil|n/?a|not applicable)\b", re.IGNORECASE)

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y",
                "%B %d, %Y", "%Y/%m/%d")

POSITIONS = ("PAYABLE", "NOT PAYABLE", "REFERRED")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


def _position(summary) -> str:
    """Normalised position. NOT PAYABLE must be tested before PAYABLE — it contains it."""
    raw = summary.get("position").upper()
    for candidate in ("NOT PAYABLE", "REFERRED", "PAYABLE"):
        if candidate in raw:
            return candidate
    return ""


# --------------------------------------------------------------------- the four assertions


def assert_claim_number(summary, case: dict) -> Check:
    """A1 — the claim number is echoed, in CLM-YYYY-NNNNN form, and is the right one."""
    value = summary.get("claim number")
    if not value:
        return Check("claim_number_format", False, "no 'Claim number:' line in the summary")
    match = CLAIM_NUMBER.search(value)
    if not match:
        return Check("claim_number_format", False,
                     f"'{value[:40]}' is not CLM-YYYY-NNNNN")

    expected = CLAIM_NUMBER.search(case.get("notes", ""))
    if expected and match.group(0) != expected.group(0):
        # Well-formed but belonging to a different claim. Worse than malformed: it looks
        # correct and would file the summary against the wrong claim.
        return Check("claim_number_format", False,
                     f"echoed {match.group(0)}, claim file says {expected.group(0)}")
    return Check("claim_number_format", True, match.group(0))


def assert_date_of_loss(summary, case: dict) -> Check:
    """A2 — the date of loss is present and actually parses to a real date."""
    value = summary.get("date of loss")
    if not value:
        return Check("date_of_loss_parseable", False, "no 'Date of loss:' line")

    cleaned = value.strip().rstrip(".")
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
        # A parseable date in the future is not a date of loss. Catching this here is why
        # "parseable" is worth more than "present".
        if parsed > date.today():
            return Check("date_of_loss_parseable", False,
                         f"{parsed.isoformat()} is in the future")
        return Check("date_of_loss_parseable", True, parsed.isoformat())
    return Check("date_of_loss_parseable", False, f"'{cleaned[:40]}' does not parse")


def assert_deductible_numeric(summary, case: dict) -> Check:
    """A3 — the excess/deductible is a numeric amount, or an explicit "none".

    "none" counts as a pass. A health claim with a co-payment and no deductible has no
    number to give, and forcing one would push the model into inventing a figure — the exact
    failure the judged criterion exists to catch.
    """
    value = summary.get("deductible")
    if not value:
        return Check("deductible_numeric", False, "no 'Deductible:' line")
    if NO_DEDUCTIBLE.match(value):
        return Check("deductible_numeric", True, "none (explicit)")
    match = AMOUNT.search(value)
    if not match:
        return Check("deductible_numeric", False,
                     f"'{value[:40]}' carries no numeric amount")
    return Check("deductible_numeric", True, match.group(0))


def assert_exclusion_cited_on_denial(summary, case: dict) -> Check:
    """A4 — a denial names an exclusion clause id; a non-denial does not invent one.

    Both directions matter. A NOT PAYABLE with no clause is an unappealable denial, which
    the claims manual forbids outright (Clause 6 requires the specific clause, quoted). A
    PAYABLE that cites an exclusion anyway is a summary that contradicts itself, and an
    adjuster skim-reading the Exclusion line would deny a payable claim.
    """
    position = _position(summary)
    value = summary.get("exclusion relied on")

    if not position:
        return Check("exclusion_cited_on_denial", False,
                     f"position '{summary.get('position')[:30]}' is not one of {POSITIONS}")

    if position == "NOT PAYABLE":
        if not value or NO_EXCLUSION.match(value):
            return Check("exclusion_cited_on_denial", False,
                         "NOT PAYABLE with no exclusion clause named")
        clause = CLAUSE_ID.search(value)
        if not clause:
            return Check("exclusion_cited_on_denial", False,
                         f"'{value[:50]}' names no clause identifier")

        # The document half: the exclusion must belong to a document the retriever actually
        # returned. A denial citing a document that was never read is a denial with no
        # evidence behind it, however well-formatted the clause number looks.
        retrieved_docs = {h.meta.get("document_id") for h in summary.hits}
        retrieved_docs.discard(None)
        if retrieved_docs and not any(doc in value for doc in retrieved_docs):
            return Check("exclusion_cited_on_denial", False,
                         f"clause '{clause.group(0)}' cited but no retrieved document is "
                         f"named in '{value[:50]}'")
        return Check("exclusion_cited_on_denial", True, clause.group(0))

    if value and not NO_EXCLUSION.match(value) and CLAUSE_ID.search(value):
        return Check("exclusion_cited_on_denial", False,
                     f"position is {position} but an exclusion is cited: {value[:40]}")
    return Check("exclusion_cited_on_denial", True, f"{position}, no exclusion cited")


_supersedes_cache: dict[str, dict] = {}


def supersession_map(corpus_id: str) -> dict[str, list[tuple[str, str]]]:
    """base document_id -> [(superseding document_id, its effective_date)].

    Built from the ``supersedes`` field the corpus front matter already carries, so this is a
    lookup and not a guess.
    """
    if corpus_id not in _supersedes_cache:
        from .config import DEFAULT_CHUNKING
        from . import store

        mapping: dict[str, list[tuple[str, str]]] = {}
        try:
            collection = store.get_collection(DEFAULT_CHUNKING, corpus_id)
            for meta in collection.get(include=["metadatas"])["metadatas"] or []:
                base, doc = meta.get("supersedes"), meta.get("document_id")
                if not base or not doc:
                    continue
                entry = (doc, meta.get("effective_date") or "")
                mapping.setdefault(base, [])
                if entry not in mapping[base]:
                    mapping[base].append(entry)
        except Exception:
            mapping = {}
        _supersedes_cache[corpus_id] = mapping
    return _supersedes_cache[corpus_id]


def assert_currency_declared(summary, case: dict) -> Check:
    """A5 — if the summary leans on a wording that a later endorsement amends, it must say so.

    ADDED IN RESPONSE TO EVIDENCE, not designed up front. Three judge prompts in a row
    (v1 88%, v2 84%, v3 88%) failed to catch two summaries that quoted a 2025 figure
    accurately and presented it as operative when a 2026 endorsement had changed it. That is
    not a weak prompt, it is an impossible question: the amending clause was never retrieved,
    so it is not in the judge's context and no amount of instruction can conjure it. Asked to
    reason about currency anyway, the judge invented justifications — v2 claimed the window
    was "confirmed as operative by passage [3] and passage [5]", which are about document
    reminders and digital submission.

    The corpus front matter has carried ``supersedes`` all along, so the question a model kept
    getting wrong is a dictionary lookup. This is the Week-6 lesson applied a second time, and
    the first time it was driven by measurement rather than by taste.

    Passes when nothing supersedes what the summary relied on, when the superseding document
    took effect after the date of loss, or when the summary names it.
    """
    if not summary.text:
        return Check("currency_declared", False, "no summary produced")

    mapping = supersession_map(case.get("corpus", ""))
    if not mapping:
        return Check("currency_declared", True, "corpus declares no supersessions")

    # What the summary leaned on: the documents on its Policy line, plus the documents behind
    # the passages it actually cited.
    relied = {d for d in mapping if d and d in summary.get("policy")}
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", summary.get("basis") or "")}
    for n in cited:
        if 1 <= n <= len(summary.hits):
            doc = summary.hits[n - 1].meta.get("document_id")
            if doc in mapping:
                relied.add(doc)
    if not relied:
        return Check("currency_declared", True, "relies on no superseded wording")

    loss = summary.get("date of loss").strip()
    for fmt in DATE_FORMATS:
        try:
            loss = datetime.strptime(loss.rstrip("."), fmt).date().isoformat()
            break
        except ValueError:
            continue
    else:
        return Check("currency_declared", True, "date of loss unparseable; check skipped")

    for base in sorted(relied):
        for doc, eff in mapping[base]:
            if eff and eff <= loss and doc not in summary.text:
                return Check("currency_declared", False,
                             f"relies on {base} but {doc} (effective {eff}) amends it before "
                             f"the {loss} date of loss and is never mentioned")
    return Check("currency_declared", True,
                 f"currency of {', '.join(sorted(relied))} accounted for")


ASSERTIONS = (
    assert_claim_number,
    assert_date_of_loss,
    assert_deductible_numeric,
    assert_exclusion_cited_on_denial,
    assert_currency_declared,
)

ASSERTION_NAMES = ("claim_number_format", "date_of_loss_parseable",
                   "deductible_numeric", "exclusion_cited_on_denial",
                   "currency_declared")


def run_assertions(summary, case: dict) -> list[Check]:
    """All five, always. Stopping at the first failure hides the other four."""
    if not summary.text:
        return [Check(name, False, f"no summary produced ({summary.reason[:60]})")
                for name in ASSERTION_NAMES]
    return [fn(summary, case) for fn in ASSERTIONS]


def citations_resolve(summary) -> Check:
    """Supporting check — the [n] markers point at passages that were really supplied.

    Not one of the four criteria moved out of the judge; it already existed in the
    question-answering path (generator.py Gate 3) and is reported alongside for context.
    """
    if not summary.text:
        return Check("citations_resolve", False, "no summary produced")
    markers = {int(n) for n in re.findall(r"\[(\d+)\]", summary.get("basis") or summary.text)}
    if not markers:
        return Check("citations_resolve", False, "Basis carries no [n] citation")
    invented = sorted(n for n in markers if not 1 <= n <= len(summary.hits))
    if invented:
        return Check("citations_resolve", False,
                     f"cites {invented} but only {len(summary.hits)} passages supplied")
    return Check("citations_resolve", True, f"cites {sorted(markers)}")
