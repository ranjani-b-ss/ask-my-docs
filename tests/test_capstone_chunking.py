"""Week 12 — the capstone reads the repaired index, and through it the exclusion list's governing bullets reach the model (needs the index)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import exclusion_reach as er                                              # noqa: E402
from src.config import DEFAULT_CHUNKING, LEGACY_CAPSTONE_SLUG, capstone_chunking


def test_the_capstone_reads_structured_chunking_and_the_default_is_untouched(monkeypatch):
    monkeypatch.delenv("CAPSTONE_CHUNKING", raising=False)
    assert capstone_chunking().strategy == "structured"
    assert DEFAULT_CHUNKING.strategy == "recursive" and LEGACY_CAPSTONE_SLUG == "recursive_800_150"


def test_the_override_selects_the_legacy_index(monkeypatch):
    monkeypatch.setenv("CAPSTONE_CHUNKING", "recursive_800_150")
    assert capstone_chunking().slug == "recursive_800_150"


def test_every_governing_bullet_reaches_the_model_on_the_structured_index_and_the_two_that_broke_did_not_on_the_old():
    new, old = er.reach("structured_800_150"), er.reach("recursive_800_150")
    assert all(new.values()), [k for k, v in new.items() if not v]
    assert not old["C-011 outside India (motor)"] and not old["C-007 hire-car bill (motor)"]


def test_any_query_naming_the_section_title_reaches_the_exclusion_section_for_both_products():
    import re
    from src.config import CANDIDATE_K, chunking_from_slug
    from src.retriever import retrieve
    cfg = chunking_from_slug("structured_800_150")
    for product in ("motor", "health"):
        for date in ("2026-02-27", "2026-04-01", "2026-07-15"):
            for q in ("What is not covered", "the section titled What is not covered", "not covered under this policy"):
                hits = retrieve(q, cfg=cfg, corpus_id="insurance", top_k=3, candidate_k=CANDIDATE_K, min_cosine=0.0,
                                min_rerank_score=0.0, loss_date=date, product=product).hits
                assert any(re.search("not covered", str(h.meta.get("section")), re.I) for h in hits), (product, date, q)
