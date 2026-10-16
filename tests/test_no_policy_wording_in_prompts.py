"""Policy wording must not appear in a prompt or a tool description.

Quoting a clause's own words as "the phrase to search with" hands the model the answer to the cases it is scored on, and
does nothing for the next clause nobody quoted (WEEK11.md §9; SEAMS.md S21). This is a general detector, not a list of the
phrases that were caught: any run of SHINGLE consecutive words that also occurs in the corpus counts as quoted wording.
Section TITLES ("What is not covered") are short and are not flagged — a title is not wording.
"""

import re
from pathlib import Path

from src import loader
from src.agent import react_agent
from src.agent import triage_agent
from src.config import CORPORA_DIR
from src.mcp_servers import wording_server

SHINGLE = 6


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _corpus_shingles() -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for doc in loader.load_corpus(CORPORA_DIR / "insurance"):
        w = _words(doc.text)
        out.update(tuple(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1))
    return out


CORPUS = _corpus_shingles()


def quoted_wording(text: str) -> list[str]:
    w = _words(text)
    return sorted({" ".join(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1) if tuple(w[i:i + SHINGLE]) in CORPUS})


def test_the_detector_flags_the_phrases_that_were_removed():
    old_prompt = ('Search with the policy\'s own phrasing of an exclusion: for example "outside the geographical area stated '
                  'in the schedule", "under the influence of intoxicating liquor".')
    found = quoted_wording(old_prompt)
    assert any("geographical area stated in the" in f for f in found) and any("influence of intoxicating liquor" in f for f in found)


def test_the_triage_prompt_quotes_no_policy_wording():
    assert quoted_wording(triage_agent.SYSTEM_PROMPT_TEMPLATE) == []


def test_the_search_wording_tool_description_quotes_no_policy_wording():
    assert quoted_wording(wording_server.search_wording.__doc__ or "") == []


def test_the_week_11_agent_prompt_quotes_no_policy_wording():
    assert quoted_wording(react_agent.SYSTEM_PROMPT) == []


def test_the_prompt_version_was_bumped():
    assert triage_agent.PROMPT_VERSION == "triage-v3"
