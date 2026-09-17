"""src/agent/budgets.py — the four stop conditions. Week 7's brief calls out "declaring the
limits but not checking all four" as the most common mistake here, so each one gets its own
test rather than one combined check that could pass by accident.
"""

from __future__ import annotations

from src.agent.budgets import Budgets, exceeded
from src.agent.usage import UsageAccumulator


def _usage(**overrides) -> UsageAccumulator:
    u = UsageAccumulator(provider="test", model="test-model")
    for k, v in overrides.items():
        setattr(u, k, v)
    return u


def test_exceeded_is_none_when_nothing_is_over():
    budgets = Budgets(max_iterations=6, max_tokens=6000, max_cost_usd=0.02, max_wall_seconds=60.0)
    assert exceeded(budgets, _usage(), iteration=0) is None


def test_exceeded_on_max_iterations():
    budgets = Budgets(max_iterations=3)
    result = exceeded(budgets, _usage(), iteration=3)
    assert result is not None
    assert "max_iterations" in result


def test_not_exceeded_one_lap_before_the_limit():
    budgets = Budgets(max_iterations=3)
    assert exceeded(budgets, _usage(), iteration=2) is None


def test_exceeded_on_max_tokens():
    budgets = Budgets(max_tokens=1000)
    usage = _usage(prompt_tokens=900, completion_tokens=200)
    result = exceeded(budgets, usage, iteration=0)
    assert result is not None
    assert "max_tokens" in result


def test_exceeded_on_max_cost():
    budgets = Budgets(max_cost_usd=0.01)
    usage = _usage(cost_usd=0.02)
    result = exceeded(budgets, usage, iteration=0)
    assert result is not None
    assert "max_cost_usd" in result


def test_exceeded_on_max_wall_seconds():
    budgets = Budgets(max_wall_seconds=1.0)
    usage = _usage()
    usage._started -= 1000   # simulate 1000s elapsed without an actual sleep
    result = exceeded(budgets, usage, iteration=0)
    assert result is not None
    assert "max_wall_seconds" in result


def test_iteration_is_checked_before_tokens_when_both_are_over():
    """Order matters only for the message shown, but the order is a real contract other code
    could come to depend on — pin it explicitly rather than leave it to reading the source."""
    budgets = Budgets(max_iterations=1, max_tokens=10)
    usage = _usage(prompt_tokens=100, completion_tokens=100)
    result = exceeded(budgets, usage, iteration=1)
    assert "max_iterations" in result
