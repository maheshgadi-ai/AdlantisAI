"""Inputs and outputs of the blind pairwise judge."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class SideScore(BaseModel):
    """Scores from 1 (poor) to 5 (excellent) for one campaign."""

    model_config = ConfigDict(extra="forbid")

    persuasiveness: int
    brand_fit: int
    clarity: int

    @field_validator("persuasiveness", "brand_fit", "clarity")
    @classmethod
    def _in_range(cls, value: int) -> int:
        if not 1 <= value <= 5:
            raise ValueError("scores run from 1 to 5")
        return value

    @property
    def total(self) -> int:
        """The sum of the three rubric scores."""
        return self.persuasiveness + self.brand_fit + self.clarity


class PairwiseVerdict(BaseModel):
    """The judge's scores for two unnamed campaigns."""

    model_config = ConfigDict(extra="forbid")

    campaign_a: SideScore
    campaign_b: SideScore
    winner: Literal["A", "B", "tie"]
    reason: str


class PairwiseRequest(BaseModel):
    """A brief and two campaigns, identified only by position."""

    model_config = ConfigDict(extra="forbid")

    brief: str
    campaign_a: str
    campaign_b: str
