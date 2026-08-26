"""Week 6 — claim summaries written from adjuster notes.

The question-answering path answers one question from the policy documents. This path does
something a claims desk actually needs: it reads an adjuster's claim file, retrieves the
policy clauses that bear on it, and writes a summary with a coverage position on it.

That output is what gets scored, so its shape is fixed rather than free prose:

    Claim number / Date of loss / Line / Policy / Position / Deductible / Exclusion / Basis

A fixed shape is what makes half the quality criteria checkable by a regex instead of by a
model (see :mod:`src.assertions`). Free prose would force every one of them through an LLM
judge, which costs money, varies between runs, and is the thing Week 6 exists to stop doing
where a rule would do.

The retrieval query is built from two fields of the notes — the incident and the coverage
question — not from the whole file. Week 5 measured why: a long, meta-phrased query
("Compare the waiting period in the base wording with the endorsement") retrieved worse than
a two-word one, and a claim file is mostly names, dates and reference numbers that dilute
the terms worth matching on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import llm
from .config import CANDIDATE_K, DEFAULT_CHUNKING, DEFAULT_CORPUS, TOP_K, ChunkConfig
from .generator import format_context
from .retriever import Hit, retrieve

SUMMARY_PROMPT_VERSION = "summary-v1"

SYSTEM_PROMPT = """\
You are an insurance claims adjuster's assistant. You write a claim summary using ONLY the \
numbered policy passages in the CONTEXT block and the facts in the CLAIM FILE.

Output EXACTLY these eight lines, in this order, with no preamble and nothing after:

Claim number: <copy verbatim from the claim file>
Date of loss: <copy from the claim file, as YYYY-MM-DD>
Line: <motor or health, from the claim file>
Policy: <document_id of the wording you relied on, plus any endorsement document_id>
Position: <PAYABLE or NOT PAYABLE or REFERRED>
Deductible: <the amount as a number with its currency, e.g. INR 3,000, or "none" if no \
deductible applies to this claim>
Exclusion relied on: <document_id and clause number, e.g. PW-MOTOR-001 Clause 3, whenever \
Position is NOT PAYABLE; otherwise "none">
Basis: <two or three sentences, each ending in a [n] citation marker>

Rules, in order of importance:
1. Every coverage position, figure, limit, waiting period and deadline in the Basis must \
come from a CONTEXT passage. Do not use general insurance knowledge and do not reason from \
what is typical. An invented policy term is worse than no summary at all.
2. If the CONTEXT does not support a position, write REFERRED and say in the Basis which \
clause you would need. Never guess a position.
3. Where an endorsement and a base wording disagree, the endorsement with the later \
effective_date prevails. Use its figure and say the earlier one was superseded.
4. Quote figures exactly as the passages state them. Never round, convert or recompute.
5. Only write NOT PAYABLE where a CONTEXT passage states an exclusion that covers these \
facts, and name that clause on the Exclusion line.
6. Cite with [n] markers that exist in the CONTEXT. Never cite a number that is not there.
"""

SUMMARY_TEMPLATE = """CONTEXT
{context}

CLAIM FILE
{notes}

Write the eight-line claim summary now, using only the CONTEXT and the CLAIM FILE."""

_FIELD = re.compile(r"^\s*([A-Za-z][A-Za-z ]*?)\s*:\s*(.*)$")

# The lines a summary is required to carry. The assertions in src/assertions.py check the
# contents; this list is only about presence.
REQUIRED_FIELDS = ("claim number", "date of loss", "line", "policy", "position",
                   "deductible", "exclusion relied on", "basis")


@dataclass
class Summary:
    case_id: str
    text: str                        # the raw model output, unmodified
    fields: dict = field(default_factory=dict)
    hits: list[Hit] = field(default_factory=list)
    grounded: bool = True
    mode: str = "llm"
    reason: str = ""
    query: str = ""
    diagnostics: dict = field(default_factory=dict)

    def get(self, name: str) -> str:
        return self.fields.get(name.lower(), "")


def parse_fields(text: str) -> dict:
    """Pull the eight labelled lines out of the model's output.

    Tolerant on purpose: a model that emits ``**Position:** PAYABLE`` or adds a stray blank
    line has still produced a usable summary, and failing it here would blame the assertions
    for a formatting wobble. What is NOT tolerated is a missing field — that is a real
    defect and the assertions must see it.
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        cleaned = line.strip().lstrip("-*# ").replace("**", "")
        match = _FIELD.match(cleaned)
        if not match:
            continue
        key = match.group(1).strip().lower()
        if key in REQUIRED_FIELDS and key not in fields:
            fields[key] = match.group(2).strip()
    return fields


def build_query(notes: str) -> str:
    """Retrieval query from the incident and the coverage question only.

    A claim file is mostly identifiers. Feeding the whole thing to the retriever spends the
    query's term budget on a claim number and a registration date, which BM25 treats as rare
    high-value tokens and the embedding treats as noise — both wrong.
    """
    wanted = ("incident", "coverage question", "adjuster note")
    parts = []
    for line in notes.splitlines():
        match = _FIELD.match(line.strip())
        if match and match.group(1).strip().lower() in wanted:
            parts.append(match.group(2).strip())
    return " ".join(parts) if parts else notes.strip()


def summarise(
    case_id: str,
    notes: str,
    cfg: ChunkConfig = DEFAULT_CHUNKING,
    corpus_id: str = DEFAULT_CORPUS,
    top_k: int = TOP_K,
    candidate_k: int = CANDIDATE_K,
    provider: str | None = None,
    model: str | None = None,
    min_cosine: float = 0.0,
    min_rerank_score: float = 0.0,
) -> Summary:
    """Retrieve the relevant clauses, then write the summary.

    The abstain gates default to 0.0 here, unlike the question-answering path. A claim file
    always deserves a summary: if the corpus cannot support a position the right output is
    ``Position: REFERRED`` naming the clause that is missing, which is useful to an adjuster.
    Refusing to write anything is not — it loses the claim number, the date of loss and the
    facts, which are all in the notes and none of which needed the corpus.
    """
    query = build_query(notes)
    retrieval = retrieve(query, cfg=cfg, corpus_id=corpus_id, top_k=top_k,
                         candidate_k=candidate_k, min_cosine=min_cosine,
                         min_rerank_score=min_rerank_score)

    diagnostics = dict(retrieval.diagnostics)
    diagnostics.update(prompt_version=SUMMARY_PROMPT_VERSION, query=query)

    if not retrieval.hits:
        return Summary(case_id, "", {}, [], False, "no_context",
                       "Nothing retrieved for this claim file.", query, diagnostics)

    context = format_context(retrieval.hits)
    try:
        raw = llm.chat(SYSTEM_PROMPT,
                       SUMMARY_TEMPLATE.format(context=context, notes=notes.strip()),
                       provider=provider, model=model)
    except Exception as exc:
        return Summary(case_id, "", {}, retrieval.hits, False, "provider_error",
                       str(exc)[:300], query, diagnostics)

    diagnostics.update(provider=provider or llm.provider_name(),
                       model=model or llm.default_model(provider),
                       params=llm.call_params(provider))
    return Summary(case_id, raw, parse_fields(raw), retrieval.hits, True,
                   llm.provider_name(), "", query, diagnostics)
