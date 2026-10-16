"""Week 12 — the trajectory scorer must be able to fail (offline, hand-built traces)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
import cap_trajectory_eval as te                                              # noqa: E402

FULL = te.gold_for("CLM-2026-00601", "2026-03-31")
LAPSED = te.gold_for("CLM-2026-00603", "2026-05-20")


def _trace(*calls):
    spans = []
    for c in calls:
        name, flag = (c if isinstance(c, tuple) else (c, None))
        spans.append({"source": "host", "kind": "tool", "tool": name,
                      "ok": flag != "failed", "blocked": flag == "blocked"})
    return {"spans": spans}


def test_gold_comes_from_the_registry():
    assert FULL["in_force"] and len(FULL["route"]) == 5
    assert not LAPSED["in_force"] and LAPSED["forbidden"] == {"search_wording", "get_limits"}


def test_the_minimal_route_is_clean():
    s = te.score_trajectory(_trace(*te.IN_FORCE_ROUTE), FULL)
    assert s["trajectory_clean"] and s["tool_choice_accuracy"] == 1.0 and s["extra_calls"] == 0


def test_a_failed_call_makes_the_route_unclean_even_though_it_was_retried():
    s = te.score_trajectory(_trace("lookup_policy", "check_in_force", ("search_wording", "failed"),
                                   "search_wording", "get_limits", "refer_to_adjuster"), FULL)
    assert not s["trajectory_clean"] and s["failed"] == 1 and s["tool_choice_accuracy"] < 1.0


def test_a_blocked_premature_referral_is_counted():
    s = te.score_trajectory(_trace("lookup_policy", "check_in_force", ("refer_to_adjuster", "blocked"),
                                   "search_wording", "get_limits", "refer_to_adjuster"), FULL)
    assert s["blocked"] == 1 and not s["trajectory_clean"]


def test_searching_wording_on_a_lapsed_policy_is_forbidden():
    s = te.score_trajectory(_trace("lookup_policy", "check_in_force", "search_wording",
                                   "refer_to_adjuster"), LAPSED)
    assert s["forbidden_ran"] == ["search_wording"] and not s["trajectory_clean"]


def test_the_lapsed_route_is_three_calls_and_clean():
    assert te.score_trajectory(_trace(*te.LAPSED_ROUTE), LAPSED)["trajectory_clean"]


def test_missing_required_tool_and_wrong_order_are_caught():
    s = te.score_trajectory(_trace("lookup_policy", "check_in_force", "refer_to_adjuster"), FULL)
    assert s["missing"] == ["search_wording", "get_limits"] and not s["trajectory_clean"]
    s = te.score_trajectory(_trace("lookup_policy", "get_limits", "check_in_force", "search_wording",
                                   "refer_to_adjuster"), FULL)
    assert not s["in_order"]
