"""Week 12 — the judge-validation harness must be able to fail (offline: no model, no index)."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
import cap_judge_agreement as ag                                                  # noqa: E402
import planted_cap as pc                                                          # noqa: E402


def test_the_frozen_labels_file_has_not_been_edited():
    expected = (ROOT / "eval" / "labels_cap_70.sha256").read_text().split()[0]
    actual = hashlib.sha256((ROOT / "eval" / "labels_cap_70.json").read_bytes()).hexdigest()
    assert actual == expected, "labels_cap_70.json changed after it was frozen — record changes in labels_cap_70_revisions.json"


def test_every_label_has_a_split_and_a_reason():
    labels = json.loads((ROOT / "eval" / "labels_cap_70.json").read_text())["labels"]
    assert len(labels) == 70
    assert all(v["label"] in ("GROUNDED", "UNGROUNDED") and v["split"] in ("dev", "test") and v["reason"]
               for v in labels.values())


def test_a_claim_never_straddles_the_dev_test_split():
    labels = json.loads((ROOT / "eval" / "labels_cap_70.json").read_text())["labels"]
    split_of = {}
    for key, v in labels.items():
        claim = key.split(":")[1]
        assert split_of.setdefault(claim, v["split"]) == v["split"], f"{claim} appears in both splits"


def test_kappa_is_zero_for_chance_and_one_for_perfect_agreement():
    assert ag.kappa([("G", "G")] * 9 + [("U", "U")]) == 1.0
    always_g = [("G", "G")] * 9 + [("U", "G")]                         # judge says G for everything
    assert abs(ag.kappa(always_g)) < 1e-9


def test_agreement_equal_to_the_baseline_gives_no_credit():
    pairs = [("G", "G")] * 9 + [("U", "G")]
    assert sum(h == j for h, j in pairs) / len(pairs) == 0.9 and ag.kappa(pairs) == 0.0


def test_a_tied_vote_is_a_flag_not_a_pass():
    assert ag.majority([{"verdict": "GROUNDED"}, {"verdict": "UNGROUNDED"}]) == "UNGROUNDED"
    assert ag.majority([{"verdict": "ERROR"}, {"verdict": "GROUNDED"}]) == "GROUNDED"
    assert ag.majority([{"verdict": "ERROR"}]) == "ERROR"


def test_provider_errors_are_not_scored():
    assert ag.majority([{"verdict": "ERROR"}, {"verdict": "ERROR"}]) == "ERROR"


def test_every_planted_edit_changes_exactly_what_it_says_and_controls_are_grounded():
    planted = json.loads((ROOT / "eval" / "planted_cap.json").read_text())
    specs = {e[0]: e for e in pc.EDITS}
    assert len(planted) == len(specs) == 30
    for p in planted:
        _, _, _, old, new, typ = specs[p["id"]]
        assert old in p["original_text"] and p["edited_text"] == p["original_text"].replace(old, new, 1)
        assert p["edited_text"] != p["original_text"]
        assert p["label"] == ("GROUNDED" if typ == "ctrl" else "UNGROUNDED")


def test_wilson_interval_widens_with_small_n():
    lo_small, hi_small = ag.wilson(9, 10)
    lo_big, hi_big = ag.wilson(900, 1000)
    assert (hi_small - lo_small) > (hi_big - lo_big)
