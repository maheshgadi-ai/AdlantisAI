"""Token cost calculation and run-level usage totals."""

from __future__ import annotations

import threading

from pydantic import BaseModel, Field, PrivateAttr

from adlantis.config.models import Pricing
from adlantis.llm.types import Usage


def cost_of(usage: Usage, pricing: Pricing) -> tuple[float, float]:
    """Return (input_cost, output_cost) in USD for one call, with cache reads/writes priced."""
    read = pricing.cache_read_per_mtok
    write = pricing.cache_write_per_mtok
    input_cost = (
        usage.uncached_input_tokens * pricing.input_per_mtok
        + usage.cache_read_tokens * (pricing.input_per_mtok if read is None else read)
        + usage.cache_write_tokens * (pricing.input_per_mtok if write is None else write)
    )
    return input_cost / 1_000_000, usage.output_tokens * pricing.output_per_mtok / 1_000_000


class RoleUsage(BaseModel):
    """Usage totals for one role or for the whole run."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        """Sum of input and output tokens."""
        return self.input_tokens + self.output_tokens

    def add(self, usage: Usage, cost_usd: float) -> None:
        """Add one call to these totals."""
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_tokens
        self.cache_write_tokens += usage.cache_write_tokens
        self.cost_usd += cost_usd


class RunUsage(RoleUsage):
    """Run totals plus a per-role breakdown. Safe to update from several threads."""

    by_role: dict[str, RoleUsage] = Field(default_factory=dict)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def record(self, usage: Usage, cost_usd: float = 0.0, role: str = "default") -> None:
        """Add one call's usage and cost to the run and role totals."""
        with self._lock:
            self.add(usage, cost_usd)
            self.by_role.setdefault(role, RoleUsage()).add(usage, cost_usd)
