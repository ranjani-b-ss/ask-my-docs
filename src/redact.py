"""Strip claimant identifiers out of text *before* it reaches the trace file.

This runs on the way in, not as a cleanup pass afterwards. The difference matters: a
redaction step that runs after writing means the raw identifier existed on disk, and on
a shared machine or in a git history "we deleted it later" is not a defence. Every field
that lands in traces/traces.jsonl passes through :func:`scrub` first, so the unredacted
string is never persisted at all.

What is deliberately NOT redacted: policy wording figures, section numbers, dates, sums
insured, and deductibles. Those are the whole point of the trace — over-redacting numbers
would make the traces unreadable and the error analysis impossible. The patterns below are
therefore anchored on identifier *shapes* and on words that introduce a person's name,
not on "any number".
"""

from __future__ import annotations

import re

# --- identifiers ---------------------------------------------------------------------

# CLM-2026-004871, CLAIM/2026/8812, claim no. 4471902, POL-TN-99231
_CLAIM_ID = re.compile(
    r"\b(?:CLM|CLAIM|CLM_NO|POL|POLICY|PROP|PROPOSAL|CERT)[\s:/#-]{0,3}"
    r"(?:NO\.?|NUMBER|ID)?[\s:/#-]{0,3}"
    r"(?=[A-Z0-9/-]*\d)[A-Z0-9]{2,}(?:[/-][A-Z0-9]{2,}){0,3}\b",
    re.IGNORECASE,
)

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Indian mobile numbers, with or without +91 and separators.
_PHONE = re.compile(r"(?:\+?91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b")

# Aadhaar is exactly 12 digits, usually grouped 4-4-4. Sums insured are not written this way.
_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")

# PAN: five letters, four digits, one letter.
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

# Bank / UTR style long digit runs (13+) that no policy figure ever reaches.
_LONG_DIGITS = re.compile(r"\b\d{13,}\b")

# --- names ---------------------------------------------------------------------------

# Names are only redacted where a cue word introduces them, and then only when the run of
# capitalised words looks like a person rather than a defined policy term.
#
# The first version of this pattern accepted a SINGLE capitalised word after a cue. On real
# traffic that destroyed 14 of 124 traces: insurance prose puts capitalised defined terms
# directly after exactly these cues, so "Insured Person Pays", "Sum Insured Band" and
# "in-patient Care and Day care" all came out as "[REDACTED]". Over-redaction is not the
# safe direction — it silently deletes the evidence the log exists to preserve.
#
# So a candidate now needs TWO or more capitalised words (a personal name in this domain
# always has at least a given and a family name) and none of them may be policy vocabulary.
# The deliberate cost: "claimant Rajesh asked" — a bare single first name with no title — is
# no longer caught. In this corpus a lone capitalised word after a cue is almost always a
# defined term, so the single-word rule did far more damage than good.
# The case-insensitive flag is scoped to the CUE ONLY, deliberately. Applying it to the
# whole pattern (as the first version did) makes [A-Z] match lowercase, so the name run
# swallows the words after the name — "patient Meera Nair was denied" captured
# "Meera Nair was", hit "was" in the stoplist, and skipped a real claimant name. A
# case-blind capital letter is a contradiction, and here it silently inverted the outcome.
_NAME_CUE = re.compile(
    r"\b(?i:(claimant|insured person|insured|policyholder|policy holder|patient|"
    r"proposer|nominee|beneficiary|member|assured))\b"
    r"(?:\s+(?i:is|was|named|name))?"
    r"[\s:,]{1,3}"
    r"((?:Mr|Mrs|Ms|Dr|Shri|Smt|Sri)\.?\s+)?"
    r"([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){1,2})"
)

# A title always introduces a name, cue word or not.
_TITLED_NAME = re.compile(
    r"\b(Mr|Mrs|Ms|Dr|Shri|Smt|Sri)\.?\s+"
    r"([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){0,2})"
)

REDACTED = "[REDACTED]"

# Cue words are followed by ordinary policy vocabulary far more often than by a name.
# Without this list, "the insured Person shall" becomes "the insured [REDACTED] shall".
_NOT_A_NAME = {
    "person", "persons", "shall", "must", "may", "will", "has", "have", "had", "is",
    "was", "were", "means", "declared", "hospital", "hospitals", "event", "events",
    "amount", "sum", "policy", "policies", "claim", "claims", "section", "sections",
    "under", "and", "or", "the", "any", "all", "such", "who", "whose", "for", "from",
    "date", "dates", "period", "periods", "treatment", "expenses", "deductible",
    "declaration", "details", "eligible", "entitled", "name", "names", "bank",
    "hospitalisation", "hospitalization", "member", "members", "network", "day", "days",
    # Added after reading real traces: every one of these appeared capitalised directly
    # after a cue word and was redacted as if it were a claimant's name.
    "care", "band", "pays", "paid", "opts", "per", "department", "insured", "sub",
    "limit", "limits", "up", "along", "with", "provides", "submits", "avails", "opting",
    "officer", "grievance", "redressal", "room", "rent", "cover", "covered", "benefit",
    "benefits", "illness", "injury", "in", "out", "co", "payment", "bonus", "cumulative",
    "waiting", "exclusion", "exclusions", "schedule", "certificate", "table", "annexure",
}


def _scrub_named(match: re.Match) -> str:
    cue, title, name = match.group(1), match.group(2) or "", match.group(3)
    # Every word must look like part of a person's name. Checking only the first word let
    # "Sum Insured Per Day" through on the strength of "Per" not being listed.
    if any(word.lower() in _NOT_A_NAME for word in name.split()):
        return match.group(0)          # policy vocabulary, not a person
    return f"{cue} {title}{REDACTED}".replace("  ", " ")


def _scrub_titled(match: re.Match) -> str:
    name = match.group(2)
    if name.split()[0].lower() in _NOT_A_NAME:
        return match.group(0)
    return f"{match.group(1)}. {REDACTED}"


def scrub(text: str | None) -> str | None:
    """Return ``text`` with claimant identifiers replaced by ``[REDACTED]``.

    Idempotent, and safe on None so callers do not need to branch.
    """
    if not text:
        return text
    out = _EMAIL.sub(REDACTED, text)
    out = _AADHAAR.sub(REDACTED, out)
    out = _PAN.sub(REDACTED, out)
    out = _LONG_DIGITS.sub(REDACTED, out)
    out = _PHONE.sub(REDACTED, out)
    out = _CLAIM_ID.sub(REDACTED, out)
    out = _NAME_CUE.sub(_scrub_named, out)
    out = _TITLED_NAME.sub(_scrub_titled, out)
    return out


def scrub_deep(value):
    """Recursively scrub every string inside a dict/list structure."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {k: scrub_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_deep(v) for v in value]
    return value


def contains_identifier(text: str | None) -> bool:
    """True if any redaction pattern still matches — used by the self-test in trace.py."""
    if not text:
        return False
    return any(
        p.search(text)
        for p in (_EMAIL, _AADHAAR, _PAN, _LONG_DIGITS, _PHONE, _CLAIM_ID, _TITLED_NAME)
    )
