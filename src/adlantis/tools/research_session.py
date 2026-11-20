"""The gate between the researcher's model and the web.

Every call the model makes passes through here, so the limits below hold no matter what the
model was persuaded to attempt: only URLs returned by search can be read, budgets are fixed,
and web text reaches the model only after sanitizing, scanning, and wrapping.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Callable
from typing import Any, NamedTuple

from pydantic import BaseModel, ValidationError

from adlantis.schemas.evidence import Evidence
from adlantis.schemas.evidence_store import EvidenceRecord, EvidenceStore, canonical_url
from adlantis.schemas.research import (
    FetchRequest,
    ResearchLimits,
    ResearchStats,
    SearchRequest,
    ToolFailure,
)
from adlantis.tools.registry import ToolRegistry
from adlantis.tools.source_quality import SourceQualityScorer
from adlantis.tools.untrusted import injection_signals, render_untrusted, sanitize

logger = logging.getLogger(__name__)

MAX_CAUSE_CHARS = 120


class SessionTool(NamedTuple):
    """A tool as offered to the model."""

    name: str
    description: str
    schema: type[BaseModel]


SESSION_TOOLS = (
    SessionTool(
        "web_search",
        "Search the web for market trends, competitor positioning, and audience insights.",
        SearchRequest,
    ),
    SessionTool(
        "fetch_url", "Read one page that web_search returned during this run.", FetchRequest
    ),
)


class ResearchSession:
    """Runs the model's tool calls for one research run."""

    def __init__(
        self,
        tools: ToolRegistry,
        scorer: SourceQualityScorer,
        limits: ResearchLimits,
        *,
        nonce: Callable[[], str] = lambda: secrets.token_hex(12),
    ) -> None:
        self.store = EvidenceStore()
        self.stats = ResearchStats()
        self._tools = tools
        self._scorer = scorer
        self._limits = limits
        self._nonce = nonce
        self._readable: set[str] = set()

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Run one tool call and return the text the model may see."""
        if name == "web_search":
            return self._search(arguments)
        if name == "fetch_url":
            return self._fetch(arguments)
        return self._refuse(f"unknown tool {name[:60]}")

    def _search(self, arguments: dict[str, Any]) -> str:
        request = _parse(SearchRequest, arguments)
        if request is None:
            return self._refuse("invalid web_search arguments")
        if self.stats.searches >= self._limits.max_searches:
            return self._refuse("search budget used")
        self.stats.searches += 1
        args = {"query": request.query, "max_results": self._limits.results_per_search}
        records = self._run("web_search", args)
        if records is None:
            return _status("failed", "The search could not be completed.")
        self._readable |= {r.canonical_url for r in records if r.status == "usable"}
        return self._render(records)

    def _fetch(self, arguments: dict[str, Any]) -> str:
        request = _parse(FetchRequest, arguments)
        if request is None:
            return self._refuse("invalid fetch_url arguments")
        if canonical_url(request.url) not in self._readable:
            return self._refuse(f"URL was not returned by search: {request.url[:200]}")
        if self.stats.fetches >= self._limits.max_fetches:
            return self._refuse("fetch budget used")
        self.stats.fetches += 1
        records = self._run(
            "fetch_url", {"url": request.url, "max_chars": self._limits.fetch_chars}
        )
        if records is None:
            return _status("failed", "The page could not be read.")
        return self._render(records)

    def _run(self, tool: str, args: dict[str, Any]) -> list[EvidenceRecord] | None:
        result = self._tools.run(tool, args)
        if not result.ok:  # the error text can quote the remote server, so it is never relayed
            self.stats.failed_calls += 1
            target = str(args.get("url") or args.get("query") or "")
            self.stats.tool_failures.append(
                ToolFailure(tool=tool, target=target, cause=failure_cause(result.error))
            )
            logger.warning("research tool failed", extra={"tool": tool})
            return None
        return [record for item in result.data if (record := self._admit(item)) is not None]

    def _admit(self, item: Evidence) -> EvidenceRecord | None:
        rating = self._scorer.rate(item.source_url)
        if rating.tier == "blocked":
            self.stats.blocked_sources += 1
            return None
        title, excerpt = sanitize(item.title), sanitize(item.snippet)
        return self.store.add(
            url=item.source_url,
            title=title,
            excerpt=excerpt,
            tool=item.tool,
            rating=rating,
            published=item.published,
            injection_signals=injection_signals(f"{item.source_url}\n{title}\n{excerpt}"),
            hidden_blocks=int(item.metadata.get("hidden_blocks", 0)),
        )

    def _render(self, records: list[EvidenceRecord]) -> str:
        withheld = [r.id for r in records if r.status == "quarantined"]
        content = render_untrusted(records, self._nonce())
        return json.dumps({"status": "ok", "withheld_sources": withheld}) + "\n" + content

    def _refuse(self, reason: str) -> str:
        self.stats.refused_calls.append(reason)
        logger.warning("research call refused", extra={"reason": reason})
        return _status("refused", reason)


def failure_cause(error: str | None) -> str:
    """Why a tool call failed, leaving out any text quoted from the remote server."""
    lines = (error or "").splitlines()
    summary = lines[0] if lines else "unknown error"
    return summary.split(": ", 1)[-1].split(" - ", 1)[0][:MAX_CAUSE_CHARS]


def _parse(schema: type[BaseModel], arguments: dict[str, Any]) -> Any | None:
    try:
        return schema.model_validate(arguments)
    except ValidationError:
        return None


def _status(status: str, reason: str) -> str:
    return json.dumps({"status": status, "reason": reason})
