"""Week 12 — the loss-date and product filter in src/retriever.py.

Pure and model-free: Hit objects are built by hand, nothing is embedded or searched. The
boundary cases are the ones that matter — the day before an endorsement takes effect, and the
day it takes effect — because an off-by-one on a date comparison is exactly the bug that
cites the wrong wording for a loss that lands on the line.
"""

from src.retriever import Hit, in_force_hits


def _hit(doc_id, effective, lob="motor", chunk="c"):
    meta = {"document_id": doc_id, "line_of_business": lob}
    if effective is not None:
        meta["effective_date"] = effective
    return Hit(text=doc_id, meta=meta, cosine=0.9, chunk_id=f"{doc_id}::{chunk}")


BASE = _hit("PW-MOTOR-001", "2025-04-01")
END = _hit("END-2026-01", "2026-04-01")


def _ids(hits):
    return [h.meta["document_id"] for h in hits]


def test_loss_the_day_before_the_endorsement_drops_it():
    kept, dropped = in_force_hits([BASE, END], "2026-03-31", None)
    assert _ids(kept) == ["PW-MOTOR-001"]
    assert dropped == 1


def test_loss_on_the_effective_day_keeps_the_endorsement():
    kept, dropped = in_force_hits([BASE, END], "2026-04-01", None)
    assert _ids(kept) == ["PW-MOTOR-001", "END-2026-01"]
    assert dropped == 0


def test_loss_well_after_keeps_both():
    kept, _ = in_force_hits([BASE, END], "2026-06-01", None)
    assert _ids(kept) == ["PW-MOTOR-001", "END-2026-01"]


def test_loss_before_the_base_wording_drops_everything():
    kept, dropped = in_force_hits([BASE, END], "2025-03-31", None)
    assert kept == []
    assert dropped == 2


def test_product_scope_drops_other_lines_but_keeps_all():
    health = _hit("END-2026-02", "2026-05-01", lob="health")
    defs = _hit("PW-DEFS-004", "2025-04-01", lob="all")
    kept, dropped = in_force_hits([BASE, health, defs], None, "motor")
    assert _ids(kept) == ["PW-MOTOR-001", "PW-DEFS-004"]
    assert dropped == 1


def test_undated_chunk_is_kept_not_guessed_at():
    undated = _hit("PLACEHOLDER", None)
    kept, dropped = in_force_hits([undated], "2024-01-01", None)
    assert _ids(kept) == ["PLACEHOLDER"]
    assert dropped == 0


def test_no_filters_is_a_no_op():
    kept, dropped = in_force_hits([BASE, END], None, None)
    assert kept == [BASE, END]
    assert dropped == 0


def test_date_and_product_compose():
    health = _hit("END-2026-02", "2026-05-01", lob="health")
    kept, dropped = in_force_hits([BASE, END, health], "2026-03-31", "motor")
    assert _ids(kept) == ["PW-MOTOR-001"]
    assert dropped == 2
