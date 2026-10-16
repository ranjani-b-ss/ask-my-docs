#!/usr/bin/env python
"""Does the exclusion list's governing bullet reach the model when it searches for the policy's "What is not covered" section?

    python eval/exclusion_reach.py

Retrieval only (no model), through the capstone's real path: product + loss-date filter, top 3. The query is the one the exclusions
gate tells the model to use. The markers below are the governing bullet's words, taken from the corpus and used ONLY to check the result —
they appear in no prompt. Run on the legacy `recursive` index and the `structured` one.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import CANDIDATE_K, chunking_from_slug                     # noqa: E402
from src.retriever import retrieve                                         # noqa: E402

QUERY = "What is not covered"
CASES = [
    ("CLM-2026-00514 liquor (motor)", "motor", "2026-04-18", "intoxicating liquor"),
    ("CLM-2026-00561 tyres alone (motor)", "motor", "2026-06-02", "50% of the cost of replacement"),
    ("C-011 outside India (motor)", "motor", "2026-05-10", "outside the geographical area stated in the schedule"),
    ("C-007 hire-car bill (motor)", "motor", "2026-03-01", "hire charges for a\n  replacement vehicle"),
    ("CLM-2026-00509 alcohol (health)", "health", "2026-05-04", "treatment for alcoholism, drug or substance abuse"),
    ("CLM-2026-00567 outside India (health)", "health", "2026-04-25", "treatment taken outside India"),
    ("CLM-2026-00442 non-medical items (health)", "health", "2026-02-27",
     "non-medical items listed in Annexure C, including gloves, administrative charges"),
]


def reach(slug: str) -> dict[str, bool]:
    cfg = chunking_from_slug(slug)
    out = {}
    for name, product, date, marker in CASES:
        hits = retrieve(QUERY, cfg=cfg, corpus_id="insurance", top_k=3, candidate_k=CANDIDATE_K, min_cosine=0.0,
                        min_rerank_score=0.0, loss_date=date, product=product).hits
        out[name] = any(marker in h.text for h in hits)
    return out


if __name__ == "__main__":
    old, new = reach("recursive_800_150"), reach("structured_800_150")
    print(f"query {QUERY!r}, top-3, product + loss-date filter\n\n{'case':<46}{'recursive':<11}structured")
    for name, *_ in CASES:
        print(f"{name:<46}{'HIT' if old[name] else 'miss':<11}{'HIT' if new[name] else 'miss'}")
    print(f"\ngoverning bullet in front of the model: recursive {sum(old.values())}/{len(CASES)}   structured {sum(new.values())}/{len(CASES)}")
    (ROOT / "eval" / "exclusion_reach_results.json").write_text(json.dumps({"query": QUERY, "recursive": old, "structured": new}, indent=1))
