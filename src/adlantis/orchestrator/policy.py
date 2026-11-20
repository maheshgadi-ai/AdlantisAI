"""Per-agent retries and timeouts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import TypeVar

from adlantis.llm.budget import BudgetExceeded
from adlantis.llm.types import LLMError

logger = logging.getLogger(__name__)

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class AgentTimeout(LLMError):
    """An agent did not finish within its time limit."""


@dataclass(frozen=True)
class AgentPolicy:
    """How long one agent call may take and how many times it may be repeated."""

    timeout_seconds: float = 600.0
    retries: int = 1


DEFAULT_POLICIES: dict[str, AgentPolicy] = {
    "researcher": AgentPolicy(timeout_seconds=900.0, retries=0),  # a repeat would re-bill searches
    "strategist": AgentPolicy(),
    "copywriter": AgentPolicy(),
    "claim_checker": AgentPolicy(),
    "designer": AgentPolicy(),
    "baseline": AgentPolicy(timeout_seconds=900.0),
}


def call_with_policy(
    work: Callable[[InputT], OutputT], data: InputT, policy: AgentPolicy, name: str = "agent"
) -> OutputT:
    """Run `work`, repeating model failures. A budget stop is final and is never repeated.

    Raises:
        AgentTimeout: If the last attempt ran out of time.
        LLMError: If the last attempt failed.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return _with_timeout(work, data, policy.timeout_seconds, name)
        except BudgetExceeded:
            raise
        except LLMError:
            if attempt > policy.retries:
                raise
            logger.warning("agent attempt failed", extra={"agent": name, "attempt": attempt})


def _with_timeout(
    work: Callable[[InputT], OutputT], data: InputT, seconds: float, name: str
) -> OutputT:
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(work, data).result(timeout=seconds)
    except FutureTimeout as exc:
        raise AgentTimeout(f"{name} did not finish within {seconds:.0f} seconds.") from exc
    finally:
        pool.shutdown(wait=False)


class GuardedChecker:
    """A claim checker that follows its policy inside the review loop."""

    def __init__(self, checker, policy: AgentPolicy) -> None:
        self._checker = checker
        self._policy = policy

    def run(self, data):
        """Check one asset."""
        return call_with_policy(self._checker.run, data, self._policy, "claim_checker")


class GuardedReviser:
    """A copywriter that follows its policy inside the review loop."""

    def __init__(self, reviser, policy: AgentPolicy) -> None:
        self._reviser = reviser
        self._policy = policy

    def revise(self, data):
        """Propose edits for one asset."""
        return call_with_policy(self._reviser.revise, data, self._policy, "copywriter")
