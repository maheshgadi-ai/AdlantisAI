"""Web search via Tavily (https://docs.tavily.com/documentation/api-reference/endpoint/search)."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from adlantis.schemas.evidence import Evidence
from adlantis.schemas.titles import clean_title
from adlantis.tools.base import ToolError
from adlantis.tools.http import EvidenceTool

API_URL = "https://api.tavily.com/search"
_SNIPPET_CHARS = 1500


class WebSearchArgs(BaseModel):
    """Arguments for `web_search`."""

    query: str = Field(min_length=1, max_length=400, description="What to search the web for.")
    max_results: int = Field(default=5, ge=1, le=10)
    topic: Literal["general", "news", "finance"] = "general"
    time_range: Literal["day", "week", "month", "year"] | None = Field(
        default=None, description="Only return results from this recent period."
    )
    include_domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=20)


class WebSearchTool(EvidenceTool[WebSearchArgs]):
    """General web search through Tavily; returns ranked pages with relevant excerpts."""

    name = "web_search"
    description = (
        "Search the web for market trends, competitor positioning, and audience insights. "
        "Returns page titles, URLs, relevant excerpts, and a relevance score."
    )
    args_schema = WebSearchArgs
    timeout_seconds: ClassVar[float] = 30.0
    # `basic` costs 1 credit per call; `advanced` costs 2.
    search_depth: ClassVar[str] = "basic"

    def __init__(self, *, api_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not api_key:
            raise ValueError("WebSearchTool needs a Tavily API key (TAVILY_API_KEY)")
        self._api_key = api_key

    def _run(self, args: WebSearchArgs) -> list[Evidence]:
        body: dict[str, Any] = {
            "query": args.query,
            "max_results": args.max_results,
            "search_depth": self.search_depth,
            "topic": args.topic,
            "include_answer": False,
            "include_raw_content": False,
        }
        if args.time_range:
            body["time_range"] = args.time_range
        if args.include_domains:
            body["include_domains"] = args.include_domains
        if args.exclude_domains:
            body["exclude_domains"] = args.exclude_domains
        response = self._send(
            "POST", API_URL, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
        )
        return parse_results(response.json(), tool=self.name)


def parse_results(payload: Any, *, tool: str) -> list[Evidence]:
    """Turn a Tavily search response into Evidence items."""
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ToolError(f"{tool}: unexpected response shape from Tavily")
    evidence: list[Evidence] = []
    for item in payload["results"]:
        url = item.get("url")
        if not url:
            continue
        evidence.append(
            Evidence(
                source_url=url,
                title=clean_title(item.get("title") or "", url, text=item.get("content")),
                snippet=(item.get("content") or "")[:_SNIPPET_CHARS],
                tool=tool,
                published=item.get("published_date") or None,
                score=item.get("score"),
            )
        )
    return evidence
