"""Week 12 bonus — the straddle cases are permanent eval cases.

Retrieval-level, model-free, needs the index. They pin three things:
  * the day-before cases are DISCRIMINATING — at least 5 are red with no loss date (otherwise "green after" proves nothing);
  * with the loss date supplied, every day-before case is clean: the in-force clause is in the top 3 and no chunk from a
    document not yet in force is;
  * the filter costs no hit@3 on the control questions at any of the three loss dates.
"""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
import straddle_bonus as sb                                                   # noqa: E402
import version_check as vc                                                    # noqa: E402

TOPICS = yaml.safe_load((ROOT / "eval" / "version_cases.yaml").read_text())["topics"]


@pytest.fixture(scope="module")
def rows():
    assert not vc.validate_markers(TOPICS, vc.all_chunks())
    return vc.run_boundary(TOPICS)


def _clean(r):
    return r["in_force_in_top3"] and not r["stale_in_top3"]


def _day_before(rows, cond):
    return {r["topic"]: r for r in rows if r["kind"] == "day_before" and r["condition"] == cond}


def test_at_least_five_day_before_cases_are_red_without_the_loss_date(rows):
    red = [t for t, r in _day_before(rows, "baseline").items() if not _clean(r)]
    assert len(red) >= 5, f"only {len(red)} day-before cases fail without the filter — they would not discriminate"


def test_every_day_before_case_is_clean_with_the_loss_date(rows):
    bad = [t for t, r in _day_before(rows, "scoped").items() if not _clean(r)]
    assert not bad, bad


def test_the_filter_never_returns_a_wrong_version_at_rank_one_on_a_day_before_loss(rows):
    assert not [t for t, r in _day_before(rows, "scoped").items() if r["wrong_first"]]


def test_the_filter_costs_no_hit_at_3_on_the_control_questions():
    c = sb.cost(sb.control_questions())
    assert c["n_questions"] == 22
    assert all(d["lost"] == 0 for d in c["per_date"].values()), c["changes"]


def test_the_ablation_switch_defaults_to_filter_on(monkeypatch):
    sys.path.insert(0, str(ROOT))
    from src.mcp_servers import wording_server as ws
    monkeypatch.delenv("WORDING_DATE_FILTER", raising=False)
    assert ws.date_filter_enabled()
    monkeypatch.setenv("WORDING_DATE_FILTER", "off")
    assert not ws.date_filter_enabled()
