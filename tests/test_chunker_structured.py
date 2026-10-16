"""Week 11 follow-up — the `structured` chunking strategy, and the failure that motivated it.

Root cause (WEEK11.md, drill.md): the corpus hard-wraps its lines and `recursive` packs PHYSICAL lines, so the motor exclusion
list (~1,050 chars against an 800 target) was cut mid-bullet. The tail — "hire charges for a / replacement vehicle" and the
geographical-area bullet — landed in a 253-character stub that begins mid-line and that no natural query retrieved. These
tests pin the repair and the exact set of sections it changed.
"""

import re

from src import chunker, loader
from src.config import CORPORA_DIR, ChunkConfig

DOCS = loader.load_corpus(CORPORA_DIR / "insurance")
REC = chunker.chunk_corpus(DOCS, ChunkConfig("recursive", 800, 150))
STR = chunker.chunk_corpus(DOCS, ChunkConfig("structured", 800, 150))


def _holding(chunks, needle):
    return [c for c in chunks if needle in c.text]


def test_a_wrapped_bullet_is_one_atom():
    text = ("The Company is not liable for:\n\n- normal wear and tear;\n- consequential loss, including loss of use and hire charges for a\n"
            "  replacement vehicle;\n- loss outside the geographical area.\n")
    atoms = [a for a in chunker._logical_atoms(text) if a.strip()]
    assert "- consequential loss, including loss of use and hire charges for a\n  replacement vehicle;" in atoms
    assert len(atoms) == 4


def test_the_motor_exclusion_list_is_one_chunk_with_every_bullet():
    held = _holding(STR, "outside the geographical area stated in the schedule")
    assert len(held) == 1
    text = held[0].text
    for must in ("The Company is not liable for", "valid and\n  effective driving licence", "intoxicating liquor",
                 "used for hire or reward", "hire charges for a\n  replacement vehicle"):
        assert must in text, must


def test_recursive_still_cuts_it_which_is_the_defect_this_fixes():
    geo = _holding(REC, "outside the geographical area stated in the schedule")
    assert len(geo) == 1 and "The Company is not liable for" not in geo[0].text      # the stub, cut from its list
    assert geo[0].text[0].islower()                                                    # and it starts mid-line


def test_no_structured_chunk_starts_in_the_middle_of_a_line():
    bad = [(c.chunk_id, c.text[:40]) for c in STR if c.text.strip()[0].islower()]
    assert not bad, bad


def test_no_structured_chunk_is_a_stub():
    assert min(c.meta["n_chars"] for c in STR) >= 250


def test_only_four_sections_differ_from_recursive():
    """The blast radius, pinned. Anything else changing is a surprise to be looked at, not absorbed."""
    def key(c):
        return (c.meta["document_id"], c.meta["section"].split(">")[-1].strip())
    r_text = {(c.meta["document_id"], c.text) for c in REC}
    s_text = {(c.meta["document_id"], c.text) for c in STR}
    changed = {key(c) for c in REC if (c.meta["document_id"], c.text) not in s_text}
    changed |= {key(c) for c in STR if (c.meta["document_id"], c.text) not in r_text}
    assert changed == {("PW-MOTOR-001", "3. What is not covered"), ("PW-HEALTH-002", "6. What is not covered"),
                       ("PW-HEALTH-002", "8. Claims — reimbursement"), ("PW-DEFS-004", "2. Definitions")}


def test_the_health_exclusion_list_had_the_same_defect_and_is_repaired():
    held = _holding(STR, "treatment for alcoholism, drug or substance abuse")
    assert len(held) == 1 and "non-medical items listed in Annexure C" in held[0].text


def test_the_default_chunking_is_untouched():
    from src.config import DEFAULT_CHUNKING
    assert DEFAULT_CHUNKING.strategy == "recursive"          # Week 12's index and every stored chunk id depend on this
