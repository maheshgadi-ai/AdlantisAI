"""Inputs and outputs of the single-prompt baseline."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from adlantis.schemas.brand import BrandKit
from adlantis.schemas.channels import Channel
from adlantis.schemas.copy import CampaignAsset, DraftVariant
from adlantis.schemas.facts import FactSheet
from adlantis.schemas.product import ProductBrief
from adlantis.schemas.review import AssetGap


class BaselineChannel(BaseModel):
    """The copy written for one channel."""

    model_config = ConfigDict(extra="forbid")

    channel: Channel
    variants: list[DraftVariant] = Field(default_factory=list)


class BaselineDraft(BaseModel):
    """A whole campaign from one model response."""

    model_config = ConfigDict(extra="forbid")

    positioning: str
    concept: str
    channels: list[BaselineChannel] = Field(default_factory=list)


class BaselineRequest(BaseModel):
    """Everything the single prompt works from."""

    model_config = ConfigDict(extra="forbid")

    brand: BrandKit
    product: ProductBrief
    facts: FactSheet
    today: date


class BaselineResult(BaseModel):
    """The baseline's assets, and any variants that could not be used."""

    positioning: str
    concept: str
    assets: list[CampaignAsset] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    gaps: list[AssetGap] = Field(default_factory=list)
