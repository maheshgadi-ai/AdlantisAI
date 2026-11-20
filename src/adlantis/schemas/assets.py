"""Campaign copy as the rules engine and claim checker receive it."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from adlantis.schemas.channels import AssetChannel


class AssetCopy(BaseModel):
    """One piece of copy: named text fields plus the facts and evidence it cites."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1)
    channel: AssetChannel
    fields: dict[str, str] = Field(min_length=1)
    references: list[str] = Field(default_factory=list)
