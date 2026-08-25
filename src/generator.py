"""Stage 6 — grounded generation with citations.

Three things keep the model honest:

1. **Numbered context only.** The prompt contains the retrieved passages and nothing
   else. The model is told its own prior knowledge is off-limits.
2. **Mandatory citations.** Every sentence must carry a ``[n]`` marker pointing at the
   passage that supports it. A claim with no marker has nowhere to hide.
3. **A verification pass after generation.** We check that the markers the model emitted
   actually exist. A model that invents ``[7]`` when five passages were supplied is
   drifting, and we downgrade the answer rather than show it.

If Ollama is not running the module falls back to ``extractive`` mode, which quotes the
best passage verbatim instead of writing prose. Retrieval, citation, and abstention all
still work — you simply get a quote instead of a sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import llm
from .config import OLLAMA_MODEL, OLLAMA_URL
from .retriever import Hit, Retrieval

SYSTEM_PROMPT = """\
You are a careful insurance claims assistant. You answer ONLY from the numbered passages \
given to you in the CONTEXT block.

Rules, in order of importance:
1. If the CONTEXT does not contain the answer, reply with exactly: NOT_IN_DOCUMENTS
   Do not guess, do not use general knowledge, do not reason from what is "typical" in \
insurance. A plausible-sounding invented policy term is the worst possible output.
2. Every factual sentence must end with a citation marker naming the passage it came \
from, like [1] or [2][3]. Never cite a number that is not in the CONTEXT.
3. Quote exact figures, limits, percentages, waiting periods, and deadlines from the \
passages. Never round, convert, or recompute them.
4. If an endorsement and a base policy wording disagree, the endorsement with the later \
effective_date prevails. Say explicitly that the earlier wording was superseded, give the \
current position first, and cite both passages.
5. Distinguish a deductible from a co-payment, and a sum insured from a limit, exactly as \
the passages do. Do not treat them as interchangeable.
6. Be brief. Two or three sentences is usually right. No preamble, no restating the \
question, no disclaimers about consulting a professional.
"""

ANSWER_TEMPLATE = """CONTEXT
{context}

QUESTION
{question}

Answer using only the CONTEXT above, with a [n] citation on every factual sentence. \
If the CONTEXT does not answer the question, reply exactly NOT_IN_DOCUMENTS."""

NOT_FOUND_TOKEN = "NOT_IN_DOCUMENTS"
_CITATION = re.compile(r"\[(\d+)\]")

# The prompt identity, recorded in every trace.
#
# The version string is the human label; the hash is the proof. A version alone is a
# promise that someone remembered to bump it, and the one time they don't is the one time
# a whole week of traces becomes unreplayable. Comparing the hash catches that silently.
PROMPT_VERSION = "claims-v1"

# Context truncation is part of the prompt, so it belongs to the recorded version: the same
# passages assembled at a different width are a different model call.
MAX_CHARS_PER_HIT = 1800


def prompt_sha() -> str:
    from .trace import sha

    return sha(SYSTEM_PROMPT + "\x00" + ANSWER_TEMPLATE + "\x00" + str(MAX_CHARS_PER_HIT))


@dataclass
class Answer:
    text: str
    grounded: bool
    citations: list[dict] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    mode: str = "llm"
    reason: str = ""
    diagnostics: dict = field(default_factory=dict)


def provider_available(provider: str | None = None) -> tuple[bool, str]:
    """Is the configured LLM reachable? Drives the retrieval-only fallback."""
    status = llm.status(provider)
    return status.ready, status.detail


# Kept for the CLI's status command, which reports on Ollama specifically.
def ollama_available(url: str = OLLAMA_URL) -> tuple[bool, str]:
    status = llm.ollama_status(url)
    return status.ready, status.detail


def format_context(hits: list[Hit], max_chars_per_hit: int = MAX_CHARS_PER_HIT) -> str:
    blocks = []
    for i, hit in enumerate(hits, start=1):
        meta = hit.meta
        header = (
            f"[{i}] document_id={meta.get('document_id')} | "
            f"title={meta.get('title')} | "
            f"section={meta.get('section') or '-'} | "
            f"effective_date={meta.get('effective_date') or 'unknown'}"
        )
        body = hit.text[:max_chars_per_hit]
        blocks.append(f"{header}\n{body}")
    return "\n\n---\n\n".join(blocks)


def _call_llm(question: str, context: str, provider: str | None, model: str | None) -> str:
    """Temperature 0 everywhere: the same question must give the same answer, or the
    citation-verification gate below would be untestable."""
    return llm.chat(
        SYSTEM_PROMPT,
        ANSWER_TEMPLATE.format(context=context, question=question),
        provider=provider,
        model=model,
    )


def _cited_indices(text: str, n_hits: int) -> tuple[list[int], list[int]]:
    used, invented = [], []
    for match in _CITATION.finditer(text):
        idx = int(match.group(1))
        if 1 <= idx <= n_hits:
            if idx not in used:
                used.append(idx)
        elif idx not in invented:
            invented.append(idx)
    return used, invented


def _extractive_answer(retrieval: Retrieval, why: str = "", extra: dict | None = None) -> Answer:
    """Quote the winning passage instead of writing prose.

    ``why`` must state what actually happened. "No local model running" was hardcoded from
    when Ollama was the only provider; with four providers an exhausted API quota and a
    missing local install are different problems, and a stale label sends you after the
    wrong one.
    """
    best = retrieval.hits[0]
    # Provider errors already end in a full stop; appending another reads as a typo.
    reason = (why or "no answer model is configured").strip().rstrip(".")
    return Answer(
        text=(
            f"**Retrieval-only mode** — {reason}. Showing the supporting passage "
            f"verbatim instead of a written answer:\n\n> "
            + best.text.strip().replace("\n", "\n> ")
        ),
        grounded=True,
        citations=[_citation_dict(1, best)],
        hits=retrieval.hits,
        mode="extractive",
        diagnostics={**retrieval.diagnostics, **(extra or {})},
    )


def _citation_dict(index: int, hit: Hit) -> dict:
    return {
        "n": index,
        "label": hit.citation(),
        "document_id": hit.meta.get("document_id"),
        "title": hit.meta.get("title"),
        "section": hit.meta.get("section"),
        "page": hit.meta.get("page"),
        "effective_date": hit.meta.get("effective_date"),
        "source_url": hit.meta.get("source_url"),
        "relpath": hit.meta.get("relpath"),
        "score": hit.score,
        "snippet": hit.text[:400],
    }


def answer_from_retrieval(
    retrieval: Retrieval,
    model: str | None = None,
    provider: str | None = None,
    force_extractive: bool = False,
) -> Answer:
    # Everything a trace needs about the generation call, filled in as we go. It is built
    # here rather than at the call site because only this function knows which gate fired.
    gen = {
        "prompt_version": PROMPT_VERSION,
        "prompt_sha": prompt_sha(),
        "provider": provider or llm.provider_name(),
        "model": model or llm.default_model(provider),
        "params": llm.call_params(provider),
        "raw_output": None,
        "context_sha": None,
    }

    # Gate 1 — retrieval already decided the corpus cannot support an answer.
    if not retrieval.grounded:
        return Answer(
            text=(
                "I don't know — that isn't covered in the documents I have.\n\n"
                f"_Why: {retrieval.reason}_"
            ),
            grounded=False,
            hits=retrieval.hits,
            mode="abstained",
            reason=retrieval.reason,
            # No model was called, so record no model: writing one into the trace would
            # imply a call that never happened.
            diagnostics={**retrieval.diagnostics, **gen, "provider": None, "model": None,
                         "params": {}},
        )

    if force_extractive:
        return _extractive_answer(retrieval, "you asked for this mode",
                                  {**gen, "provider": None, "model": None, "params": {}})
    if not llm.is_ready(provider):
        return _extractive_answer(retrieval, llm.status(provider).detail,
                                  {**gen, "gate": "provider_unavailable"})

    context = format_context(retrieval.hits)
    from .trace import sha

    gen["context_sha"] = sha(context)
    try:
        raw = _call_llm(retrieval.query, context, provider, model)
    except Exception as exc:
        name = provider or llm.provider_name()
        fallback = _extractive_answer(retrieval, f"the {name} call failed. {exc}",
                                      {**gen, "gate": "provider_error",
                                       "error": str(exc)[:400]})
        fallback.reason = f"LLM call failed ({exc}); fell back to retrieval-only."
        return fallback

    gen["raw_output"] = raw

    # Gate 2 — the model itself declined.
    if NOT_FOUND_TOKEN in raw.upper():
        return Answer(
            text=(
                "I don't know — that isn't covered in the documents I have.\n\n"
                "_Why: passages were retrieved, but the model judged that none of them "
                "actually answer the question._"
            ),
            grounded=False,
            hits=retrieval.hits,
            mode="abstained",
            reason="Model returned NOT_IN_DOCUMENTS.",
            diagnostics={**retrieval.diagnostics, **gen, "gate": "model"},
        )

    # Gate 3 — verify the citations point at passages that were really supplied.
    used, invented = _cited_indices(raw, len(retrieval.hits))
    diagnostics = {**retrieval.diagnostics, **gen}
    diagnostics.update(cited=used, invented_citations=invented)

    if not used:
        return Answer(
            text=(
                "I found relevant passages but the model produced an answer without "
                "citing any of them, so I am not showing it. The passages are below — "
                "please read them directly."
            ),
            grounded=False,
            hits=retrieval.hits,
            mode="unverified",
            reason="Answer contained no valid citation markers.",
            diagnostics={**diagnostics, "gate": "citation"},
        )

    citations = [_citation_dict(i, retrieval.hits[i - 1]) for i in used]
    return Answer(
        text=raw,
        grounded=True,
        citations=citations,
        hits=retrieval.hits,
        mode=llm.provider_name(),
        reason=(
            f"Model cited non-existent passage(s) {invented}; ignored." if invented else ""
        ),
        diagnostics=diagnostics,
    )
