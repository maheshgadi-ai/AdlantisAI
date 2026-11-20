"""Marketing channels and the length limits of their copy fields."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

Channel = Literal["search_ad", "meta_ad", "instagram", "linkedin", "x", "email", "landing_page"]
KitSection = Literal["strategy", "image_prompt"]
AssetChannel = Channel | KitSection
SECTION_CHANNELS: frozenset[str] = frozenset(get_args(KitSection))
CHANNEL_PLAN_PREFIX = "strategy-channel-"


def is_channel_plan(asset_id: str) -> bool:
    """True for a strategy section that describes how one channel will be used."""
    return asset_id.startswith(CHANNEL_PLAN_PREFIX)


CountingMethod = Literal["characters", "double_width", "x_weighted"]
LimitSeverity = Literal["error", "warning"]
LimitSourceType = Literal["platform", "guideline", "editorial"]


class LimitSource(BaseModel):
    """Where a limit comes from and how far that source can be trusted."""

    model_config = ConfigDict(extra="forbid")

    type: LimitSourceType
    third_party: bool
    reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def _editorial_limits_are_our_own(self) -> LimitSource:
        if self.type == "editorial" and self.third_party:
            raise ValueError("an editorial limit cannot come from a third party")
        return self


class TruncationPoint(BaseModel):
    """Where a platform folds longer text behind "see more". Passing it only warns."""

    model_config = ConfigDict(extra="forbid")

    max_chars: int = Field(gt=0)
    severity: Literal["warning"] = "warning"
    source: LimitSource

    @model_validator(mode="after")
    def _is_a_guideline(self) -> TruncationPoint:
        if self.source.type != "guideline":
            raise ValueError("a truncation point must come from a guideline source")
        return self


class FieldLimit(BaseModel):
    """The maximum length of one copy field, how it is counted, and what exceeding it means."""

    model_config = ConfigDict(extra="forbid")

    max_chars: int = Field(gt=0)
    counting: CountingMethod = "characters"
    severity: LimitSeverity
    source: LimitSource
    truncation: TruncationPoint | None = None

    @model_validator(mode="after")
    def _only_platform_rejections_block(self) -> FieldLimit:
        if (self.severity == "error") != (self.source.type == "platform"):
            raise ValueError("platform limits are errors; guideline and editorial are warnings")
        if self.truncation and self.truncation.max_chars >= self.max_chars:
            raise ValueError("a truncation point must be shorter than the hard cap")
        return self

    @property
    def target_chars(self) -> int:
        """The length copy should aim for."""
        return self.truncation.max_chars if self.truncation else self.max_chars


class ChannelLimits(BaseModel):
    """Field limits for every channel."""

    model_config = ConfigDict(extra="forbid")

    channels: dict[Channel, dict[str, FieldLimit]]

    def writing_targets(self, channel: AssetChannel) -> dict[str, int]:
        """The length copy should aim for in each field, including non-blocking limits."""
        limits = self.channels.get(channel, {})
        return {name: limit.target_chars for name, limit in limits.items()}
