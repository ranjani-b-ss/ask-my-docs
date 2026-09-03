"""The four stop conditions the agent loop enforces so it can never spin forever.

Four numbers alone are not a safety mechanism — the Week 7 brief's own list of common
mistakes names exactly this failure: "defining MAX_ITERS, MAX_TOKENS, MAX_COST as constants
and never checking three of them in the loop." ``exceeded()`` below is the single function
``react_agent.py`` calls before every lap; all four budgets are checked there, in the same
place, so it is not possible to add a fifth budget later and forget to wire it in.
"""

from __future__ import annotations

from dataclasses import dataclass

from .usage import UsageAccumulator


@dataclass(frozen=True)
class Budgets:
    max_iterations: int = 6
    max_tokens: int = 6000
    max_cost_usd: float = 0.02
    max_wall_seconds: float = 60.0


def exceeded(budgets: Budgets, usage: UsageAccumulator, iteration: int) -> str | None:
    """Which budget is breached, checked BEFORE starting the next lap — or None.

    Order matters only for the message shown; a run that is simultaneously over budget on
    two counts is over budget, full stop. Checked ahead of the LLM call rather than after,
    because a call already in flight cannot be un-made — the loop can only refuse to start
    another one.
    """
    if iteration >= budgets.max_iterations:
        return f"max_iterations ({budgets.max_iterations})"
    if usage.total_tokens >= budgets.max_tokens:
        return f"max_tokens ({budgets.max_tokens}, used {usage.total_tokens})"
    if usage.cost_usd >= budgets.max_cost_usd:
        return f"max_cost_usd (${budgets.max_cost_usd:.4f}, spent ${usage.cost_usd:.4f})"
    if usage.elapsed_seconds() >= budgets.max_wall_seconds:
        return (f"max_wall_seconds ({budgets.max_wall_seconds}s, "
                f"elapsed {usage.elapsed_seconds():.1f}s)")
    return None
