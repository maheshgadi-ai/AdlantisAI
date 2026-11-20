"""Source-quality ratings attached to evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

QualityTier = Literal["high", "medium", "low", "unrated", "blocked"]
"""`unrated`: no rule matched. Unknown is not the same as weak, so it's neutral."""


class SourceRating(BaseModel):
    """How much weight a source deserves, from the configured domain rules."""

    score: float = Field(ge=0.0, le=1.0)
    tier: QualityTier
    label: str = Field(description="Kind of source, e.g. 'academic', 'government', 'video'.")
    rule: str = Field(description="The rule that matched, e.g. 'domain:arxiv.org' or 'default'.")

    def tag(self) -> str:
        """Compact form for prompts: 'high 0.90 academic'."""
        return f"{self.tier} {self.score:.2f} {self.label}"
