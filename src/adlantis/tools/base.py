"""Common tool pattern: typed args, retry with backoff, tracing, errors as data.

Tools never call LLMs. Agents turn `name`, `description`, and
`parameters_schema()` into a tool spec for the model.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel, ValidationError

from adlantis.observability.tracing import Tracer
from adlantis.tools.cache import ToolCache

logger = logging.getLogger(__name__)

ArgsT = TypeVar("ArgsT", bound=BaseModel)


class ToolError(RuntimeError):
    """A tool failure that retrying won't fix (bad input, 4xx, parse error)."""


class TransientToolError(ToolError):
    """A tool failure worth retrying (timeout, connection error, 5xx, rate limit).

    `retry_after` (seconds), when the server sent one, raises the next backoff delay.
    """

    def __init__(
        self, message: str, *, retry_after: float | None = None, status: int | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.status = status


class ToolResult(BaseModel):
    """What a tool returns. Failures are data, so the model can see and react to them."""

    tool: str
    ok: bool
    data: Any = None
    error: str | None = None
    attempts: int = 1
    cached: bool = False


class BaseTool(ABC, Generic[ArgsT]):
    """Base class for every tool.

    Subclasses set `name`, `description`, and `args_schema`, implement `_run`, and
    use `timeout_seconds` for their HTTP calls. `_run` should raise
    `TransientToolError` for retryable failures and `ToolError` for the rest.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    args_schema: ClassVar[type[BaseModel]]
    timeout_seconds: ClassVar[float] = 15.0
    max_attempts: ClassVar[int] = 3
    backoff_base_seconds: ClassVar[float] = 0.5
    # Bump when a tool's behavior changes so old cached results are ignored.
    cache_version: ClassVar[int] = 1

    def __init__(
        self,
        *,
        tracer: Tracer | None = None,
        sleep: Callable[[float], None] = time.sleep,
        cache: ToolCache | None = None,
    ) -> None:
        self.tracer = tracer or Tracer()
        self._sleep = sleep
        self._cache = cache

    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's arguments."""
        return self.args_schema.model_json_schema()

    def run(self, args: ArgsT | dict[str, Any]) -> ToolResult:
        """Validate args and run the tool inside a `tool` trace span, with retries."""
        with self.tracer.observe(f"tool.{self.name}", as_type="tool", input=_as_json(args)) as obs:
            result = self._run_validated(args)
            obs.update(
                output=result.model_dump(mode="json"),
                level="DEFAULT" if result.ok else "WARNING",
            )
        return result

    def _run_validated(self, args: ArgsT | dict[str, Any]) -> ToolResult:
        try:
            parsed = cast(ArgsT, self.args_schema.model_validate(args))
        except ValidationError as exc:
            return ToolResult(tool=self.name, ok=False, error=f"Invalid arguments: {exc}")
        if self._cache is None:
            return self._run_with_retries(parsed)

        key_args = {"args": parsed.model_dump(mode="json"), "v": self.cache_version}
        hit = self._cache.get(self.name, key_args)
        if hit is not None:
            logger.info("tool cache hit", extra={"tool": self.name, "tool_args": key_args["args"]})
            return ToolResult(tool=self.name, ok=True, data=self._load_cached(hit), cached=True)
        result = self._run_with_retries(parsed)
        if result.ok and result.data:  # empty results aren't cached: they may improve
            self._cache.put(self.name, key_args, result.model_dump(mode="json")["data"])
        return result

    def _load_cached(self, data: Any) -> Any:
        """Rebuild result data from its cached JSON form. Override for typed results."""
        return data

    def _run_with_retries(self, parsed: ArgsT) -> ToolResult:
        attempt = 1
        while True:
            try:
                return ToolResult(tool=self.name, ok=True, data=self._run(parsed), attempts=attempt)
            except TransientToolError as exc:
                if attempt >= self.max_attempts:
                    return self._failure(exc, attempt)
                delay = max(self.backoff_base_seconds * 2 ** (attempt - 1), exc.retry_after or 0)
                logger.warning(
                    "tool attempt failed; retrying",
                    extra={"tool": self.name, "attempt": attempt, "delay_s": delay},
                )
                self._sleep(delay)
                attempt += 1
            except ToolError as exc:
                return self._failure(exc, attempt)

    def _failure(self, exc: ToolError, attempts: int) -> ToolResult:
        logger.warning("tool failed", extra={"tool": self.name, "error": str(exc)})
        return ToolResult(tool=self.name, ok=False, error=str(exc), attempts=attempts)

    @abstractmethod
    def _run(self, args: ArgsT) -> Any:
        """Do the work and return JSON-serializable data."""


def _as_json(args: BaseModel | dict[str, Any]) -> Any:
    return args.model_dump(mode="json") if isinstance(args, BaseModel) else args
