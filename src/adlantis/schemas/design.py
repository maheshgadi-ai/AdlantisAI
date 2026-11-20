"""Inputs and outputs of the visual designer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from adlantis.schemas.brand import BrandKit
from adlantis.schemas.channels import Channel
from adlantis.schemas.copy import CampaignAsset
from adlantis.schemas.product import ProductBrief
from adlantis.schemas.strategy import CampaignStrategy

TEXT_ONLY_CHANNELS: frozenset[Channel] = frozenset({"search_ad"})
AI_IMAGE_LABEL = "AI-generated image"


class DraftImagePrompt(BaseModel):
    """An image idea as the model proposes it."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    prompt: str = Field(description="The scene to generate, in one short paragraph.")
    alt_text: str = Field(description="A plain description of the image for screen readers.")


class DesignDraft(BaseModel):
    """Everything the designer model can return."""

    model_config = ConfigDict(extra="forbid")

    prompts: list[DraftImagePrompt] = Field(default_factory=list)


class DesignRequest(BaseModel):
    """The shipped assets to illustrate and the look they should share."""

    model_config = ConfigDict(extra="forbid")

    brand: BrandKit
    product: ProductBrief
    strategy: CampaignStrategy
    assets: list[CampaignAsset]


class ImagePrompt(BaseModel):
    """A prompt that passed the code checks, ready for image generation."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    channel: Channel
    prompt: str = Field(min_length=1)
    alt_text: str = Field(min_length=1)
    size: str = Field(pattern=r"^\d+x\d+$")


class RejectedImagePrompt(BaseModel):
    """An asset left without an image prompt, and why."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    reason: str


class DesignResult(BaseModel):
    """The accepted image prompts and the assets that have none."""

    prompts: list[ImagePrompt] = Field(default_factory=list)
    rejected: list[RejectedImagePrompt] = Field(default_factory=list)


class GeneratedImage(BaseModel):
    """An image saved with the kit. It is always labeled as AI-generated."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    file: str = Field(pattern=r"^images/[A-Za-z0-9_-]+\.png$")
    model: str
    alt_text: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: Literal["AI-generated image"] = AI_IMAGE_LABEL
    cost_usd: float = Field(default=0.0, ge=0)
