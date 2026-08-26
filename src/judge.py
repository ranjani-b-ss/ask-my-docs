"""Week 6 — the LLM judge, and the one criterion left for it to judge.

The prompt lives in a text file, not in this module, for a reason that matters to the
validation: the agreement figure is a property of a *specific prompt text*, so the prompt has
to be a versioned artefact you can diff (``eval/judge_v1.txt`` vs ``eval/judge_v2.txt``) and
point at in a write-up. A prompt buried in a Python string can be edited without leaving a
trace, and then "agreement went from 72% to 88%" is unfalsifiable.

The judge answers a binary. Everything else it used to grade is now in
:mod:`src.assertions`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import llm
from .config import PROJECT_ROOT
from .generator import format_context
from .trace import sha

JUDGE_DIR = PROJECT_ROOT / "eval"

GROUNDED = "GROUNDED"
UNGROUNDED = "UNGROUNDED"

_VERDICT = re.compile(r"VERDICT\s*:\s*(GROUNDED|UNGROUNDED)", re.IGNORECASE)
_WHY = re.compile(r"WHY\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)


@dataclass
class Verdict:
    case_id: str
    verdict: str            # GROUNDED | UNGROUNDED | ERROR
    why: str = ""
    raw: str = ""
    prompt_version: str = ""
    prompt_sha: str = ""
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == GROUNDED


def load_prompt(version: str = "v1") -> tuple[str, str]:
    """Return (prompt text, sha). Comment lines are stripped before the model sees it.

    The ``#`` header in each judge file explains why the prompt is the way it is. That is for
    a human reading the diff; sending it to the model would make the prompt's own design
    rationale part of the input, which is not what is being measured.
    """
    path = JUDGE_DIR / f"judge_{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"no judge prompt at {path}")
    raw = path.read_text(encoding="utf-8")
    body = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("#")).strip()
    return body, sha(body)


def judge(summary, notes: str, version: str = "v1",
          provider: str | None = None, model: str | None = None) -> Verdict:
    template, prompt_sha = load_prompt(version)

    if not summary.text:
        # Nothing to grade. Returning ERROR rather than UNGROUNDED keeps a provider outage
        # out of the agreement figure — scoring it as a failure would look like the app
        # hallucinating when in fact no summary was written.
        return Verdict(summary.case_id, "ERROR", "no summary was produced",
                       prompt_version=version, prompt_sha=prompt_sha,
                       error=summary.reason)

    prompt = template.format(
        context=format_context(summary.hits),
        notes=notes.strip(),
        summary=summary.text.strip(),
    )
    try:
        raw = llm.chat("You are a careful, sceptical auditor. You answer in the exact "
                       "format requested and nothing more.",
                       prompt, provider=provider, model=model)
    except Exception as exc:
        return Verdict(summary.case_id, "ERROR", "", prompt_version=version,
                       prompt_sha=prompt_sha, error=str(exc)[:300])

    found = _VERDICT.search(raw)
    why = _WHY.search(raw)
    return Verdict(
        summary.case_id,
        found.group(1).upper() if found else "ERROR",
        (why.group(1).strip().split("\n")[0] if why else raw.strip()[:200]),
        raw,
        version,
        prompt_sha,
        "" if found else "no VERDICT line in the judge's reply",
    )


def agreement(labels: dict[str, str], verdicts: list[Verdict]) -> dict:
    """Agreement between hand labels and judge verdicts, as a confusion matrix.

    A single percentage is not enough to act on. 80% agreement made of 20% false-GROUNDED is
    a judge that waves through invented coverage; the same 80% made of false-UNGROUNDED is a
    judge that is merely annoying. They need opposite fixes, so both are counted.
    """
    scored, agree = 0, 0
    matrix = {"both_grounded": 0, "both_ungrounded": 0,
              "judge_grounded_human_ungrounded": 0,   # judge too lenient — the dangerous one
              "judge_ungrounded_human_grounded": 0}   # judge too strict
    disagreements, skipped = [], []

    for verdict in verdicts:
        human = labels.get(verdict.case_id)
        if human is None or verdict.verdict == "ERROR":
            skipped.append(verdict.case_id)
            continue
        scored += 1
        if verdict.verdict == human:
            agree += 1
            matrix["both_grounded" if human == GROUNDED else "both_ungrounded"] += 1
        else:
            key = ("judge_grounded_human_ungrounded" if verdict.verdict == GROUNDED
                   else "judge_ungrounded_human_grounded")
            matrix[key] += 1
            disagreements.append({"case_id": verdict.case_id, "human": human,
                                  "judge": verdict.verdict, "judge_why": verdict.why})

    return {
        "scored": scored,
        "agreed": agree,
        "agreement": (agree / scored) if scored else 0.0,
        "matrix": matrix,
        "disagreements": disagreements,
        "skipped": skipped,
    }
