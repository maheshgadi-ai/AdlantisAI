"""Tool registry: the set of tools available to agents in a run."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from adlantis.config.settings import Settings
from adlantis.observability.tracing import Tracer
from adlantis.tools.base import BaseTool, ToolResult
from adlantis.tools.cache import ToolCache
from adlantis.tools.fetch_url import FetchUrlTool
from adlantis.tools.http import default_client
from adlantis.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Name → tool lookup. Unknown names come back as a failed `ToolResult`, not an error,
    so a model that invents a tool name sees what's available and can recover."""

    def __init__(self, tools: Iterable[BaseTool[Any]] = (), *, client: httpx.Client | None = None):
        self._tools: dict[str, BaseTool[Any]] = {}
        self._client = client
        for tool in tools:
            self.register(tool)

    def register(self, tool: BaseTool[Any]) -> None:
        """Add a tool. Names must be unique."""
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool[Any]:
        """Return the tool called `name`. Raises KeyError if it isn't registered."""
        return self._tools[name]

    @property
    def names(self) -> list[str]:
        """Registered tool names, in registration order."""
        return list(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[BaseTool[Any]]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def run(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Run a tool by name; unknown names return a failed result listing valid ones."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                tool=name, ok=False, error=f"Unknown tool {name!r}. Available: {self.names}"
            )
        return tool.run(args)

    def close(self) -> None:
        """Close the shared HTTP client, if this registry created one."""
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> ToolRegistry:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def build_default_registry(
    settings: Settings, *, tracer: Tracer | None = None, client: httpx.Client | None = None
) -> ToolRegistry:
    """Register every tool that can run with the current settings.

    Tools share one HTTP client. Web search is left out (with a log line) when
    `TAVILY_API_KEY` isn't set, so agents are never offered a tool that can't work.
    When `TOOL_CACHE_DIR` is set, all tools share an on-disk result cache.
    """
    owned = client is None
    http = client or default_client()
    cache = None
    if settings.tool_cache_dir:
        cache = ToolCache(settings.tool_cache_dir, ttl_seconds=settings.tool_cache_ttl_hours * 3600)
        logger.info("tool cache enabled", extra={"dir": str(settings.tool_cache_dir)})
    common: dict[str, Any] = {"client": http, "tracer": tracer, "cache": cache}
    tools: list[BaseTool[Any]] = []
    tavily_key = settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else ""
    if tavily_key:
        tools.append(WebSearchTool(api_key=tavily_key, **common))
    else:
        logger.info("web_search disabled: TAVILY_API_KEY not set")
    tools.append(FetchUrlTool(**common))
    return ToolRegistry(tools, client=http if owned else None)
