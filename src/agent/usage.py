"""Token, cost and wall-clock accounting shared by the agent and the workflow.

The agent resends the whole growing transcript on every lap of its loop — that is how a
hand-rolled ReAct loop with a single-turn ``chat()`` primitive has to work, since there is no
persistent server-side conversation. The consequence, spelled out because the Week 7 brief
calls it out as the most common mistake: **the token cost of an agent run is not the last
call's token count, it is the sum across every lap.** ``UsageAccumulator.add`` is the only
place that sum happens, so neither the loop nor the race harness can under-count it by reading
usage once at the end.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..config import price_per_million
from .. import llm


@dataclass
class UsageAccumulator:
    """Running totals for one triage task, updated after every LLM call it makes."""

    provider: str = field(default_factory=llm.provider_name)
    model: str = field(default_factory=lambda: llm.default_model())
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    _started: float = field(default_factory=time.perf_counter)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, call_usage: dict) -> None:
        price_in, price_out = price_per_million(self.provider, self.model)
        self.calls += 1
        self.prompt_tokens += call_usage.get("prompt_tokens", 0)
        self.completion_tokens += call_usage.get("completion_tokens", 0)
        self.cost_usd += (
            call_usage.get("prompt_tokens", 0) / 1_000_000 * price_in
            + call_usage.get("completion_tokens", 0) / 1_000_000 * price_out
        )

    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self._started

    def call_llm(self, system: str, user: str) -> str:
        """The one place either system should call the model — every call is metered."""
        text, call_usage = llm.chat_with_usage(system, user, provider=self.provider,
                                               model=self.model)
        self.add(call_usage)
        return text

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "llm_calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "wall_seconds": round(self.elapsed_seconds(), 3),
        }
