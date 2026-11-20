"""Inputs and outputs of the researcher."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from adlantis.schemas.evidence_store import EvidenceStore
from adlantis.schemas.inputs import CampaignInputs

FindingKind = Literal["trend", "competitor_angle", "audience_insight"]


class ResearchBrief(BaseModel):
    """What to research. It deliberately excludes the fact sheet, which research cannot touch."""

    model_config = ConfigDict(extra="forbid")

    brand_name: str
    product_name: str
    product_description: str
    target_market: str
    campaign_goals: list[str]
    competitors: list[str] = Field(default_factory=list)

    @classmethod
    def from_campaign(cls, inputs: CampaignInputs) -> ResearchBrief:
        """Take only the market context from the campaign inputs."""
        return cls(
            brand_name=inputs.brand.name,
            product_name=inputs.product.name,
            product_description=inputs.product.description,
            target_market=inputs.product.target_market,
            campaign_goals=inputs.product.campaign_goals,
            competitors=[competitor.name for competitor in inputs.brand.competitors],
        )


class ResearchLimits(BaseModel):
    """Hard bounds on one research run."""

    model_config = ConfigDict(extra="forbid")

    max_searches: int = Field(default=4, ge=1)
    max_fetches: int = Field(default=6, ge=0)
    max_turns: int = Field(default=8, ge=1)
    results_per_search: int = Field(default=5, ge=1, le=10)
    fetch_chars: int = Field(default=8000, ge=500, le=50_000)
    turn_output_tokens: int = Field(default=4000, gt=0)
    final_output_tokens: int = Field(default=8000, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)


class SearchRequest(BaseModel):
    """What the model may ask of web search."""

    query: str = Field(min_length=1, max_length=400, description="What to search the web for.")


class FetchRequest(BaseModel):
    """What the model may ask of the page reader."""

    url: str = Field(min_length=1, description="A URL returned by web_search in this run.")


class DraftFinding(BaseModel):
    """A finding as the model proposes it, before code checks it against the evidence."""

    model_config = ConfigDict(extra="forbid")

    kind: FindingKind
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    supporting_quote: str = Field(description="An exact excerpt from one of the cited sources.")


class ResearchDraft(BaseModel):
    """Everything the model can return. It has no way to express a change to facts or rules."""

    model_config = ConfigDict(extra="forbid")

    findings: list[DraftFinding] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class ResearchFinding(DraftFinding):
    """A finding that passed every grounding check."""

    id: str = Field(pattern=r"^R-[1-9]\d*$")
    source_quality: dict[str, str] = Field(default_factory=dict)


class RejectedFinding(BaseModel):
    """A proposed finding that code refused, kept for audit."""

    statement: str
    reason: str


class ToolFailure(BaseModel):
    """A web search or page read that failed, and why."""

    tool: str
    target: str
    cause: str


class ResearchStats(BaseModel):
    """What happened during a run."""

    searches: int = 0
    fetches: int = 0
    failed_calls: int = 0
    blocked_sources: int = 0
    refused_calls: list[str] = Field(default_factory=list)
    tool_failures: list[ToolFailure] = Field(default_factory=list)


class ResearchResult(BaseModel):
    """The researcher's output."""

    findings: list[ResearchFinding] = Field(default_factory=list)
    rejected: list[RejectedFinding] = Field(default_factory=list)
    evidence: EvidenceStore = Field(default_factory=EvidenceStore)
    gaps: list[str] = Field(default_factory=list)
    stats: ResearchStats = Field(default_factory=ResearchStats)
