"""A scripted model and a fake web, so research runs execute end to end without a network."""

from __future__ import annotations

import json
from typing import Any

import httpx

from adlantis.agents import Researcher
from adlantis.config import Settings, load_profile
from adlantis.llm import ModelRouter
from adlantis.schemas import ResearchBrief, ResearchLimits
from adlantis.tools import FetchUrlTool, SourceQualityScorer, ToolRegistry, WebSearchTool
from tests.fakes import MockHTTP, fake_openai_client, openai_response

BRIEF = ResearchBrief(
    brand_name="Sample Roasters",
    product_name="Hollow Reserve",
    product_description="A washed coffee.",
    target_market="Home brewers",
    campaign_goals=["Launch the harvest"],
    competitors=["Harrowfen Coffee"],
)
ARTICLE = "https://news.example.org/brewing"
ARTICLE_TEXT = (
    "Home brewers increasingly buy whole-bean coffee online and care about origin stories. "
    "Readers in the survey said tasting notes matter more to them than roast date. "
    "Subscriptions remain popular among people who brew every morning at home."
)


SNIPPET = "Home brewers increasingly buy whole-bean coffee online and care about origin stories."


def result(url: str = ARTICLE, title: str = "Brewing at home", content: str = SNIPPET) -> dict:
    return {"url": url, "title": title, "content": content, "score": 0.9}


def html(body: str, title: str = "Brewing at home") -> str:
    return f"<html><head><title>{title}</title></head><body><main>{body}</main></body></html>"


class Web:
    """Answers Tavily searches and page requests from fixed data, and records every request."""

    def __init__(
        self,
        results: list[dict] | None = None,
        pages: dict[str, httpx.Response | str] | None = None,
    ) -> None:
        self.results = [result()] if results is None else results
        self.pages = pages or {}
        self.http = MockHTTP(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.tavily.com":
            return httpx.Response(200, json={"results": self.results})
        page = self.pages.get(str(request.url))
        if isinstance(page, httpx.Response):
            return page
        if page is None:
            return httpx.Response(404)
        return httpx.Response(200, headers={"Content-Type": "text/html"}, text=page)

    @property
    def hosts(self) -> list[str]:
        return [request.url.host for request in self.http.requests]


def search(query: str = "home coffee trends", call_id: str = "s1") -> Any:
    return openai_response(None, tool_calls=[(call_id, "web_search", json.dumps({"query": query}))])


def fetch(url: str = ARTICLE, call_id: str = "f1") -> Any:
    return openai_response(None, tool_calls=[(call_id, "fetch_url", json.dumps({"url": url}))])


def stop() -> Any:
    return openai_response("I have enough sources.")


def report(*findings: dict, gaps: tuple[str, ...] = (), **extra: object) -> Any:
    payload = {"findings": list(findings), "gaps": list(gaps), **extra}
    return openai_response(None, tool_calls=[("r1", "submit_research_draft", json.dumps(payload))])


def finding(**changes: object) -> dict:
    return {
        "kind": "audience_insight",
        "statement": "Home brewers care about origin stories.",
        "evidence_ids": ["E-1"],
        "supporting_quote": "care about origin stories",
    } | changes


def researcher(
    web: Web, *responses: Any, limits: ResearchLimits | None = None
) -> tuple[Researcher, list[dict]]:
    client = fake_openai_client(*responses)
    router = ModelRouter(Settings(), load_profile("budget"), client_factory=lambda _p: client)
    common = {"client": web.http.client, "sleep": lambda _s: None}
    tools = ToolRegistry(
        [
            WebSearchTool(api_key="test-key", **common),
            FetchUrlTool(resolver=lambda _host: ["93.184.215.14"], **common),
        ]
    )
    agent = Researcher(router, tools, SourceQualityScorer.from_path(), limits)
    return agent, client.responses.create.calls


def model_saw(calls: list[dict]) -> str:
    """Everything sent to the model across the whole run."""
    return json.dumps(calls, ensure_ascii=False)


def tool_outputs(calls: list[dict]) -> list[str]:
    """The tool results in the final request, in order."""
    items = calls[-1]["input"]
    return [item["output"] for item in items if item.get("type") == "function_call_output"]
