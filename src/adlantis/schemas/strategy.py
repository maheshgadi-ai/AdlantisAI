"""Inputs and outputs of the strategist."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from adlantis.schemas.brand import BrandKit
from adlantis.schemas.channels import Channel
from adlantis.schemas.facts import FactSheet
from adlantis.schemas.product import ProductBrief
from adlantis.schemas.research import ResearchFinding


class KeyMessage(BaseModel):
    """One message the campaign will carry, tied to what supports it."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    references: list[str] = Field(min_length=1, description="Fact IDs or evidence IDs.")


class ChannelPlan(BaseModel):
    """What one channel does in the campaign."""

    model_config = ConfigDict(extra="forbid")

    channel: Channel
    role: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class CampaignStrategy(BaseModel):
    """The positioning, concept, messages, and channel mix."""

    model_config = ConfigDict(extra="forbid")

    positioning: str = Field(min_length=1)
    concept: str = Field(min_length=1)
    key_messages: list[KeyMessage] = Field(min_length=1)
    channel_mix: list[ChannelPlan] = Field(min_length=1)


class StrategyRequest(BaseModel):
    """Everything the strategist works from."""

    model_config = ConfigDict(extra="forbid")

    brand: BrandKit
    product: ProductBrief
    facts: FactSheet
    findings: list[ResearchFinding] = Field(default_factory=list)
    today: date


class StrategyResult(BaseModel):
    """A strategy whose references have been checked, and what was removed from it."""

    strategy: CampaignStrategy
    rejected_messages: list[str] = Field(default_factory=list)
