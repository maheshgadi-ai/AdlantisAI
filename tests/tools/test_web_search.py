import json

import httpx
import pytest

from adlantis.tools.base import ToolError
from adlantis.tools.web_search import API_URL, WebSearchTool, parse_results
from tests.fakes import MockHTTP, respond

PAYLOAD = {
    "query": "solid state batteries",
    "results": [
        {
            "title": "Solid-state batteries explained",
            "url": "https://example.org/ssb",
            "content": "Solid-state batteries replace the liquid electrolyte...",
            "score": 0.91,
            "raw_content": None,
            "favicon": "https://example.org/favicon.ico",
        },
        {
            "title": "",
            "url": "https://news.example.com/ssb-2026",
            "content": "A 2026 update.",
            "score": 0.75,
            "published_date": "2026-10-01",
        },
        {"title": "no url", "content": "dropped"},
    ],
    "response_time": 1.2,
    "usage": {"credits": 1},
}


def make(*responses, sleeps: list | None = None) -> tuple[WebSearchTool, MockHTTP]:
    http = MockHTTP(respond(*responses))
    sleeps = [] if sleeps is None else sleeps
    return WebSearchTool(api_key="tvly-test", client=http.client, sleep=sleeps.append), http


def test_request_shape_and_auth() -> None:
    tool, http = make(httpx.Response(200, json=PAYLOAD))
    result = tool.run({"query": "solid state batteries", "max_results": 3})

    assert result.ok
    req = http.last
    assert req.method == "POST"
    assert str(req.url) == API_URL
    assert req.headers["Authorization"] == "Bearer tvly-test"
    body = json.loads(req.content)
    assert body == {
        "query": "solid state batteries",
        "max_results": 3,
        "search_depth": "basic",
        "topic": "general",
        "include_answer": False,
        "include_raw_content": False,
    }


def test_optional_filters_sent_only_when_set() -> None:
    tool, http = make(httpx.Response(200, json=PAYLOAD))
    tool.run(
        {
            "query": "q",
            "topic": "news",
            "time_range": "week",
            "include_domains": ["nature.com"],
            "exclude_domains": ["example.net"],
        }
    )
    body = json.loads(http.last.content)
    assert body["topic"] == "news"
    assert body["time_range"] == "week"
    assert body["include_domains"] == ["nature.com"]
    assert body["exclude_domains"] == ["example.net"]


def test_parse_results() -> None:
    first, second = parse_results(PAYLOAD, tool="web_search")
    assert first.source_url == "https://example.org/ssb"
    assert first.title == "Solid-state batteries explained"
    assert first.score == 0.91
    assert first.snippet.startswith("Solid-state batteries replace")
    assert second.title == "ssb 2026"  # empty title falls back to the URL's file name
    assert second.published == "2026-10-01"


def test_unexpected_shape_raises() -> None:
    with pytest.raises(ToolError, match="unexpected response"):
        parse_results({"detail": "oops"}, tool="web_search")


def test_bad_key_not_retried() -> None:
    tool, http = make(httpx.Response(401, json={"detail": {"error": "Unauthorized"}}))
    result = tool.run({"query": "q"})
    assert not result.ok
    assert "HTTP 401" in (result.error or "")
    assert len(http.requests) == 1


def test_plan_limit_not_retried() -> None:
    tool, http = make(httpx.Response(432, json={"detail": {"error": "Plan limit exceeded"}}))
    assert not tool.run({"query": "q"}).ok
    assert len(http.requests) == 1


def test_rate_limit_honours_retry_after() -> None:
    sleeps: list[float] = []
    tool, http = make(
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json=PAYLOAD),
        sleeps=sleeps,
    )
    assert tool.run({"query": "q"}).ok
    assert sleeps == [2.0]
    assert len(http.requests) == 2


def test_requires_api_key() -> None:
    with pytest.raises(ValueError, match="TAVILY_API_KEY"):
        WebSearchTool(api_key="")


def test_max_results_bounded() -> None:
    tool, http = make()
    assert not tool.run({"query": "q", "max_results": 50}).ok
    assert http.requests == []


def test_software_metadata_titles_replaced() -> None:
    payload = {
        "results": [
            {
                "title": "Batteries and Secure Energy Transitions - Microsoft .NET",
                "url": "https://www.iea.org/files/cb39/BatteriesandSecureEnergyTransitions.pdf",
                "content": "x",
            },
            {
                "title": "Microsoft Word - final.docx",
                "url": "https://www.iea.org/files/ab12/GlobalEVOutlook2025.pdf",
                "content": "y",
            },
        ]
    }
    first, second = parse_results(payload, tool="web_search")
    assert first.title == "Batteries and Secure Energy Transitions"
    assert second.title == "Global EV Outlook 2025"
