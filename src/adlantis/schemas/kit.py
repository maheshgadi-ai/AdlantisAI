"""The packaged campaign kit and its claims appendix."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adlantis.schemas.brand import BrandColor
from adlantis.schemas.channels import AssetChannel
from adlantis.schemas.claims import ClaimType, ClaimVerdict
from adlantis.schemas.design import GeneratedImage, ImagePrompt, RejectedImagePrompt
from adlantis.schemas.ledger import IssueLedger
from adlantis.schemas.review import AssetGap, ReviewedAsset
from adlantis.schemas.rules import RuleId
from adlantis.schemas.strategy import CampaignStrategy

KitStatus = Literal["draft", "approved"]
KitMode = Literal["team", "baseline"]
CHANNEL_PLAN_LABEL = "Internal planning, not for publication."
_SIGN_OFF_FIELDS = {"status", "approval", "content_sha256", "channel_plan_label"}


class ClaimSource(BaseModel):
    """What backs a claim: an approved fact, a cited web source, or a glossary entry."""

    model_config = ConfigDict(extra="forbid")

    reference: str
    kind: Literal["fact", "evidence", "glossary"]
    text: str
    note: str = ""
    url: str = ""
    title: str = ""
    expires: date | None = None


class AppendixClaim(BaseModel):
    """One claim in the kit, its verdict, and its evidence."""

    model_config = ConfigDict(extra="forbid")

    id: str
    asset_id: str
    channel: AssetChannel
    field: str
    quote: str
    claim_type: ClaimType
    verdict: ClaimVerdict
    decided_by: Literal["model", "code"]
    rule: RuleId | None = None
    reason: str
    sources: list[ClaimSource] = Field(default_factory=list)


class Approval(BaseModel):
    """Who signed off on the kit, when, and exactly what they approved."""

    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1)
    approved_at: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KitCost(BaseModel):
    """What the run spent, in USD."""

    model_config = ConfigDict(extra="forbid")

    total_usd: float = Field(ge=0)
    model_usd: float = Field(ge=0)
    other_usd: float = Field(default=0.0, ge=0)
    cap_usd: float = Field(gt=0)
    by_role: dict[str, float] = Field(default_factory=dict)


class CampaignKit(BaseModel):
    """Everything a person needs to review a campaign. It stays a draft until they approve."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    mode: KitMode = "team"
    verified: bool = True
    status: KitStatus = "draft"
    created_at: datetime
    profile: str
    brand_name: str
    brand_colors: list[BrandColor] = Field(default_factory=list)
    product_name: str
    summary: str = ""
    strategy: CampaignStrategy | None = None
    channel_plan_label: Literal["Internal planning, not for publication."] = CHANNEL_PLAN_LABEL
    assets: list[ReviewedAsset] = Field(default_factory=list)
    verified_sections: list[ReviewedAsset] = Field(default_factory=list)
    gaps: list[AssetGap] = Field(default_factory=list)
    claims: list[AppendixClaim] = Field(default_factory=list)
    ledger: IssueLedger = Field(default_factory=IssueLedger)
    research_gaps: list[str] = Field(default_factory=list)
    image_prompts: list[ImagePrompt] = Field(default_factory=list)
    rejected_image_prompts: list[RejectedImagePrompt] = Field(default_factory=list)
    images: list[GeneratedImage] = Field(default_factory=list)
    cost: KitCost
    content_sha256: str = ""
    approval: Approval | None = None

    @model_validator(mode="after")
    def _status_matches_the_sign_off(self) -> CampaignKit:
        if (self.status == "approved") != (self.approval is not None):
            raise ValueError("a kit is approved only with a recorded sign-off")
        return self

    def compute_hash(self) -> str:
        """A fingerprint of the kit's content, excluding the sign-off itself."""
        content = self.model_dump_json(exclude=_SIGN_OFF_FIELDS)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
