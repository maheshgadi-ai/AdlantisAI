"""The product brief (`product.yaml`): what is being marketed, to whom, and where."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from adlantis.schemas.channels import Channel


class ProductBrief(BaseModel):
    """The product and the goals of this campaign."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    aliases: list[str] = Field(
        default_factory=list, description="Other names the product goes by. Names are not claims."
    )
    description: str = Field(min_length=1)
    price_point: str = Field(min_length=1)
    target_market: str = Field(min_length=1)
    campaign_goals: list[str] = Field(min_length=1)
    channels: list[Channel] = Field(min_length=1)
    quote_research: bool = Field(
        default=False, description="Allow customer-facing copy to quote survey statistics."
    )

    @property
    def names(self) -> tuple[str, ...]:
        """The product's name and every alias."""
        return (self.name, *self.aliases)

    @field_validator("channels")
    @classmethod
    def _channels_are_unique(cls, channels: list[Channel]) -> list[Channel]:
        if len(set(channels)) != len(channels):
            raise ValueError("channels must not repeat")
        return channels
