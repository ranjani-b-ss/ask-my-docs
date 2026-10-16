"""Week 12 — the code that enforces "never state a coverage decision".

The client's compliance rule: nothing automated may state a coverage decision; it may only
surface wording and facts for an adjuster. A prompt that asks for that is a request. This is
the enforcement — a check on every piece of text the MODEL wrote, run in code, with the
result recorded in the trace.

Scope, stated precisely because it decides what the check can honestly claim:

* It inspects MODEL-AUTHORED fields only (facts, reasons, summary). Wording excerpts are
  quoted from the policy by the retriever, and a clause title such as "What is not covered"
  legitimately contains the word — so text inside double quotes is not checked.
* It is a pattern check. It catches the phrasings below. It does not understand intent, so a
  determined paraphrase ("the insurer will meet this loss") would pass it. That limit is
  reported in the eval report rather than hidden, and the eval measures how often the model
  ATTEMPTS a statement (guard triggers), which is the number that matters for the prompt.
"""

from __future__ import annotations

import re

# Words that only appear when someone is stating, or leaning toward, an outcome.
_OUTCOME = re.compile(
    r"\b(?:covered|payable|admissible|declin\w*|approv\w*|reject\w*|repudiat\w*|denied|denial|"
    r"entitled|eligible\s+for\s+(?:payment|settlement)|will\s+(?:be\s+)?(?:pay|paid|settle\w*)|"
    r"should\s+(?:be\s+)?(?:pay|paid|settle\w*)|(?:is|are|was|be|been)\s+(?:excluded|included))\b",
    re.IGNORECASE,
)
_QUOTED = re.compile(r'"[^"]*"|“[^”]*”')


def states_coverage(text: str | None) -> list[str]:
    """Every outcome-stating phrase found in ``text`` outside quotation marks."""
    if not text:
        return []
    unquoted = _QUOTED.sub(" ", text)
    return [m.group(0) for m in _OUTCOME.finditer(unquoted)]


def guard_fields(fields: dict[str, str | list | None]) -> tuple[dict, list[dict]]:
    """Check each model-authored field. Returns ``(safe_fields, violations)``.

    A violating string is REPLACED, not just flagged — the offending sentence never reaches the
    packet. Each violation records the field and the matched phrases so the trace shows what
    the model tried to say.
    """
    safe: dict = {}
    violations: list[dict] = []
    for name, value in fields.items():
        if isinstance(value, list):
            kept = []
            for i, item in enumerate(value):
                hits = states_coverage(item) if isinstance(item, str) else []
                if hits:
                    violations.append({"field": f"{name}[{i}]", "matched": hits})
                    kept.append("[withheld: this line stated an outcome — for the adjuster to decide]")
                else:
                    kept.append(item)
            safe[name] = kept
        else:
            hits = states_coverage(value) if isinstance(value, str) else []
            if hits:
                violations.append({"field": name, "matched": hits})
                safe[name] = "[withheld: this text stated an outcome — for the adjuster to decide]"
            else:
                safe[name] = value
    return safe, violations
