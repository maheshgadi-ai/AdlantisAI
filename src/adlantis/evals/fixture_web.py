"""An offline web for evaluations: fixed fictional pages, read through the real extractor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from adlantis.evals.briefs import AdversarialBrief, PlantedPage
from adlantis.schemas.evidence import Evidence
from adlantis.tools.base import BaseTool, ToolError
from adlantis.tools.extract import html_to_text
from adlantis.tools.fetch_url import FetchUrlArgs
from adlantis.tools.registry import ToolRegistry
from adlantis.tools.web_search import WebSearchArgs

PAGES_PATH = Path(__file__).parent / "data" / "research_pages.yaml"
_TOPICS = {"tamsin-hollow-roasters": "coffee", "kestrune-cycles": "cycling"}
_SNIPPET_CHARS = 1500


def _evidence(page: PlantedPage, tool: str, limit: int) -> Evidence:
    extracted = html_to_text(page.html)
    metadata = {"hidden_blocks": str(extracted.hidden_blocks)} if extracted.hidden_blocks else {}
    return Evidence(
        source_url=page.url,
        title=page.title,
        snippet=extracted.text[:limit],
        tool=tool,
        metadata=metadata,
    )


class FixtureSearch(BaseTool[WebSearchArgs]):
    """Returns the brief's pages for every query, with any planted page first."""

    name = "web_search"
    description = "Search the web for market trends, competitor positioning, and audience insights."
    args_schema = WebSearchArgs

    def __init__(self, pages: list[PlantedPage], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pages = pages

    def _run(self, args: WebSearchArgs) -> list[Evidence]:
        return [_evidence(p, self.name, _SNIPPET_CHARS) for p in self.pages[: args.max_results]]


class FixtureFetch(BaseTool[FetchUrlArgs]):
    """Reads one of the brief's pages."""

    name = "fetch_url"
    description = "Read one page that web_search returned during this run."
    args_schema = FetchUrlArgs

    def __init__(self, pages: list[PlantedPage], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pages = {page.url: page for page in pages}

    def _run(self, args: FetchUrlArgs) -> list[Evidence]:
        page = self.pages.get(str(args.url))
        if page is None:
            raise ToolError(f"{self.name}: no fixture page at {args.url}")
        return [_evidence(page, self.name, args.max_chars)]


def brief_pages(brief: AdversarialBrief, path: Path = PAGES_PATH) -> list[PlantedPage]:
    """The pages this brief's research can find."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    pages = [PlantedPage.model_validate(item) for item in data[_TOPICS[brief.brand]]]
    return [brief.page, *pages] if brief.page else pages


def fixture_registry(brief: AdversarialBrief) -> ToolRegistry:
    """Research tools that never touch the network or bill for a search."""
    pages = brief_pages(brief)
    return ToolRegistry([FixtureSearch(pages), FixtureFetch(pages)])
