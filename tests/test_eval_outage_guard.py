"""The eval runner must never record a no-reply (quota/outage) run as a result, and must stop instead of burning the wall budget."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
import run_capstone_eval as rce                                                  # noqa: E402


def test_a_zero_token_run_is_an_outage():
    assert rce.is_outage({"tokens": 0}) and not rce.is_outage({"tokens": 1485})


def test_the_default_is_to_stop_after_two_consecutive_outage_claims():
    import argparse
    src = (Path(rce.__file__)).read_text()
    assert '"--stop-after-outage", type=int, default=2' in src
    assert issubclass(rce.OutageStop, Exception)
