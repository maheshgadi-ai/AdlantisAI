"""A hard spending cap shared by every billed call in a run."""

from __future__ import annotations

import threading

from adlantis.llm.pricing import RunUsage
from adlantis.llm.types import LLMError


class BudgetExceeded(LLMError):
    """The next billed call could pass the cap, so it was never sent."""


class BudgetCap:
    """Holds the most each call can cost until its real cost is known.

    Concurrent calls wait while other calls hold the money they need. A call is refused only
    when nothing still in flight could free enough room for it.
    """

    def __init__(self, limit_usd: float, usage: RunUsage | None = None) -> None:
        if limit_usd <= 0:
            raise ValueError("The budget cap must be greater than zero.")
        self.limit_usd = limit_usd
        self._usage = usage or RunUsage()
        self._other_usd = 0.0
        self._held_usd = 0.0
        self._holds = 0
        self._changed = threading.Condition()

    @property
    def spent_usd(self) -> float:
        """Everything billed so far: model calls plus search and image charges."""
        return self._usage.cost_usd + self._other_usd

    @property
    def other_usd(self) -> float:
        """Billed spending outside the chat models."""
        return self._other_usd

    def reserve(self, amount_usd: float) -> None:
        """Hold `amount_usd`, waiting for calls in flight if that could make room.

        Raises:
            BudgetExceeded: If the amount cannot fit under the cap.
        """
        with self._changed:
            while self.spent_usd + self._held_usd + amount_usd > self.limit_usd:
                if self._holds == 0:
                    raise BudgetExceeded(
                        f"Budget cap of ${self.limit_usd:.2f} reached: ${self.spent_usd:.4f} "
                        f"spent and the next call could cost ${amount_usd:.4f}."
                    )
                self._changed.wait()
            self._held_usd += amount_usd
            self._holds += 1

    def release(self, amount_usd: float) -> None:
        """Give back a hold once its real cost has been recorded."""
        with self._changed:
            self._holds -= 1
            self._held_usd = max(0.0, self._held_usd - amount_usd) if self._holds else 0.0
            self._changed.notify_all()

    def charge(self, amount_usd: float) -> None:
        """Record spending that is not a chat model call."""
        with self._changed:
            self._other_usd += amount_usd
            self._changed.notify_all()
