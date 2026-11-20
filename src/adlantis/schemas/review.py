"""The outcome of checking and revising campaign assets."""

from __future__ import annotations

from pydantic import BaseModel, Field

from adlantis.schemas.channels import AssetChannel
from adlantis.schemas.claim_check import CheckedClaim
from adlantis.schemas.copy import CampaignAsset
from adlantis.schemas.ledger import IssueLedger
from adlantis.schemas.rules import RuleViolation


class ReviewedAsset(BaseModel):
    """An asset cleared for the kit, with its claims and non-blocking warnings."""

    asset: CampaignAsset
    claims: list[CheckedClaim] = Field(default_factory=list)
    warnings: list[RuleViolation] = Field(default_factory=list)
    revisions: int = 0


class AssetGap(BaseModel):
    """An asset removed from the kit. Its copy is deliberately not carried forward."""

    asset_id: str
    channel: AssetChannel
    reason: str
    issue_ids: list[str] = Field(default_factory=list)


class ReviewOutcome(BaseModel):
    """Which assets shipped, which became gaps, and the full issue history."""

    assets: list[ReviewedAsset] = Field(default_factory=list)
    gaps: list[AssetGap] = Field(default_factory=list)
    ledger: IssueLedger = Field(default_factory=IssueLedger)
