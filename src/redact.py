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


def scrub(text: str | None, claim_ids: bool = True) -> str | None:
    """Return ``text`` with claimant identifiers replaced by ``[REDACTED]``.

    Idempotent, and safe on None so callers do not need to branch.

    ``claim_ids=False`` keeps claim and policy numbers (Week 12): they are the operational
    join key a regulator's "why was claim 4471-A declined?" starts from, and they are not
    on the client's PII line (claimant names, addresses, injuries). It also stops the
    ``CLAIM_ID`` pattern clipping policy document ids such as "Policy PW-MOTOR-001".
    """
    if not text:
        return text
    out = _EMAIL.sub(REDACTED, text)
    out = _AADHAAR.sub(REDACTED, out)
    out = _PAN.sub(REDACTED, out)
    out = _LONG_DIGITS.sub(REDACTED, out)
    out = _PHONE.sub(REDACTED, out)
    if claim_ids:
        out = _CLAIM_ID.sub(REDACTED, out)
    out = _NAME_CUE.sub(_scrub_named, out)
    out = _TITLED_NAME.sub(_scrub_titled, out)
    return out


def scrub_deep(value, claim_ids: bool = True):
    """Recursively scrub every string inside a dict/list structure."""
    if isinstance(value, str):
        return scrub(value, claim_ids=claim_ids)
    if isinstance(value, dict):
        return {k: scrub_deep(v, claim_ids) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_deep(v, claim_ids) for v in value]
    return value


def contains_identifier(text: str | None) -> bool:
    """True if any redaction pattern still matches — used by the self-test in trace.py."""
    if not text:
        return False
    return any(
        p.search(text)
        for p in (_EMAIL, _AADHAAR, _PAN, _LONG_DIGITS, _PHONE, _CLAIM_ID, _TITLED_NAME)
    )


# --- Week 12: claimant-originated free text ------------------------------------------
#
# The client's PII line is claimant NAMES, ADDRESSES and INJURIES. ``scrub`` above covers
# names (when a cue word introduces them) and identifier shapes, but a measured gap (SEAMS.md
# S8) is that addresses and injuries pass straight through and a second person introduced by
# a word it does not know ("her passenger Arjun Nair") survives.
#
# These patterns are applied ONLY to text a claimant or adjuster wrote — the FNOL, adjuster
# notes, and the model's own quotes of them — never to policy wording. Policy wording
# legitimately contains "fracture", "burns" and "laceration" (they name covered treatments);
# redacting them there would corrupt the exact evidence a log exists to preserve.
#
# Regex is a heuristic, not a guarantee. Known limits are stated in the eval report, not here.

_PERSON_CUE = re.compile(
    r"\b(?i:(passenger|driver|witness|occupant|pillion rider|rider|owner|complainant|"
    r"victim|spouse|wife|husband|son|daughter|nephew|niece|brother|sister|father|mother|"
    r"registered to|owned by|belonging to|reported by|filed by|spoke to|spoke with|contacted))\b"
    r"(?:\s+(?i:is|was|named|name))?"
    r"[\s:,]{1,3}"
    r"((?:Mr|Mrs|Ms|Dr|Shri|Smt|Sri)\.?\s+)?"
    r"([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){1,2})"
)

# Six-digit Indian PIN code. The look-arounds stop it matching inside a longer number or a
# comma-grouped amount ("1,500,000" — a comma followed by three digits, NOT any comma: a PIN
# is routinely followed by one, "Bengaluru 560038, phone ..."); the prefix check below stops
# "INR 178500".
_PIN = re.compile(r"(?<![\w,])([1-9]\d{2}\s?\d{3})(?![\w])(?!,\d{3})")
_NOT_A_PLACE = {"inr", "rs", "amount", "claimed", "estimate", "total", "sum", "idv", "claim",
                "payable", "figure", "value", "cost", "limit", "insured", "policy", "premium",
                "date", "number", "ref", "code", "amt"}
# A PIN only counts when the token before it looks like a place name: Title-case letters.
# Measured on the first integrated eval: the looser rule redacted "600000" out of
# `"amount":600000.0` (the policy limit), and a six-digit run inside the hex trace id
# `cap_cf442790a57f` — 2 of 36 traces could no longer be found by their own id.
_PLACE_BEFORE_PIN = re.compile(r"([A-Z][a-z]{2,})[\s,\-\u2013]{1,3}$")

# "address" counts as a cue only as a LABEL ("Address: ...") or as "address is ...". The first
# version also matched the bare verb, so "...to address the adjuster's question" was read as the
# start of an address and the rest of the sentence was deleted from the trace.
_ADDR_CUE = re.compile(
    r"(?i)\b(?:address\s*:|address\s+is\b|residing\s+(?:at|in)|resides\s+(?:at|in)|"
    r"resident\s+of|lives\s+at|living\s+at|"
    r"of\s+(?=(?:flat|house|h\.?\s?no|door|plot|no\.?)\b))\s*"
)

# "14 MG Road, Indiranagar, Bengaluru 560038" with no cue word in front of it.
_BARE_ADDRESS = re.compile(
    r"(?<![\d,])(?<![\d,]\s)\b\d{1,4}[A-Za-z]?(?:/\d+)?\s+[A-Z][\w.'\-]*(?:\s+[A-Z][\w.'\-]*){0,4}"
    r"(?:,\s*[A-Za-z0-9][\w .'\-/]*){1,4}?[\s,\-\u2013]+[1-9]\d{2}\s?\d{3}\b"
)

_INJURY = re.compile(
    r"\b(?i:(?:(?:severe|serious|minor|multiple|deep|compound|hairline|suspected|"
    r"traumatic)\s+)?"
    r"(?:whiplash|fractur\w*|broken\s+(?:bones?|ribs?|wrist|arm|leg|ankle|collarbone|"
    r"jaw|nose|finger|fingers)|head\s+injur\w*|concussion|lacerat\w*|bruis\w*|sprain\w*|"
    r"dislocat\w*|internal\s+(?:bleeding|injur\w*)|spinal\s+(?:injur\w*|cord)|"
    r"burn\s+injur\w*|fatalit\w*|paralys\w*|amputat\w*|neck\s+(?:pain|injur\w*)|"
    r"back\s+(?:pain|injur\w*)|chest\s+(?:pain|injur\w*)|bleeding)"
    r"(?:\s+(?:(?:to|of|on|in)\s+)?(?:the\s+)?(?:(?:left|right)\s+)?"
    r"(?:head|neck|back|chest|arm|forearm|wrist|hand|leg|knee|ankle|foot|shoulder|hip|"
    r"face|ribs?|spine|abdomen))?)\b"
)

INJURY_TAG = "[INJURY]"


def _address_end(text: str, start: int) -> int:
    """Where an address that began at ``start`` stops: at its PIN code if there is one in
    reach, else at the end of the sentence."""
    window = text[start:start + 160]
    pin = _PIN.search(window)
    if pin:
        return start + pin.end()
    stop = re.search(r"\.(?:\s+[A-Z]|\s*$)|;", window)
    return start + (stop.start() if stop else min(len(window), 100))


def _bare_address(match: re.Match) -> str:
    """A bare "14 MG Road, ..., Bengaluru 560038" only counts if it stays inside one
    sentence and is address-sized. Without this guard the first version read the tail of
    "INR 1,500,000" as a door number and ran across two sentences to a later six-digit
    amount, deleting half the text — over-redaction destroys the evidence a log is for."""
    text = match.group(0)
    if len(text) > 100 or re.search(r"\.\s", text):
        return text
    return REDACTED


def _scrub_addresses(text: str) -> str:
    pieces, pos = [], 0
    for m in _ADDR_CUE.finditer(text):
        if m.start() < pos:
            continue
        if text[m.end():].startswith(REDACTED):      # already scrubbed — keeps this idempotent
            continue
        end = _address_end(text, m.end())
        pieces.append(text[pos:m.end()])
        pieces.append(REDACTED)
        pos = end
    pieces.append(text[pos:])
    out = "".join(pieces)
    out = _BARE_ADDRESS.sub(_bare_address, out)

    def _pin(match: re.Match) -> str:
        place = _PLACE_BEFORE_PIN.search(out_for_pin[max(0, match.start() - 24):match.start()])
        if not place or place.group(1).lower() in _NOT_A_PLACE:
            return match.group(0)
        return REDACTED

    out_for_pin = out
    return _PIN.sub(_pin, out)


def scrub_claimant(text: str | None) -> str | None:
    """``scrub`` plus the claimant-text-only patterns (second persons, addresses, injuries).

    Claim and policy numbers are kept (see ``scrub``). Idempotent, safe on None.
    """
    if not text:
        return text
    out = scrub(text, claim_ids=False)
    out = _PERSON_CUE.sub(_scrub_named, out)
    out = _scrub_addresses(out)
    out = _INJURY.sub(INJURY_TAG, out)
    return out


def scrub_claimant_deep(value, keep_keys: frozenset = frozenset()):
    """``scrub_claimant`` over every string in a dict/list structure.

    ``keep_keys``: dict keys whose values are identifiers this system generated (trace ids,
    chunk ids, hashes) — structure, not free text. They are passed through untouched at any
    depth, so a pattern written for claimant prose can never corrupt the key a log is searched by.
    """
    if isinstance(value, str):
        return scrub_claimant(value)
    if isinstance(value, dict):
        return {k: (v if k in keep_keys else scrub_claimant_deep(v, keep_keys))
                for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_claimant_deep(v, keep_keys) for v in value]
    return value
