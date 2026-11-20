"""Evidence: one source found by a tool, as the researcher will store it."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Current time in UTC (separate so tests and callers can rely on tz-aware values)."""
    return datetime.now(UTC)


class Evidence(BaseModel):
    """A single source with the text the writer may cite.

    The first five fields are the core record. The rest are optional details some
    tools can provide (arXiv authors, a search score, a publication date).
    """

    source_url: str
    title: str
    snippet: str
    retrieved_at: datetime = Field(default_factory=utc_now)
    tool: str
    published: str | None = None
    authors: list[str] = Field(default_factory=list)
    score: float | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
