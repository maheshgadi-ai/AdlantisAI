"""Inputs and outputs of the copywriter."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from adlantis.schemas.assets import AssetCopy
from adlantis.schemas.brand import BrandKit
from adlantis.schemas.channels import Channel
from adlantis.schemas.facts import FactSheet
from adlantis.schemas.ledger import LedgerIssue
from adlantis.schemas.product import ProductBrief
from adlantis.schemas.research import ResearchFinding
from adlantis.schemas.strategy import CampaignStrategy

ASSET_VARIANTS: dict[Channel, int] = {
    "search_ad": 3,
    "meta_ad": 2,
    "instagram": 2,
    "linkedin": 1,
    "x": 2,
    "email": 1,
    "landing_page": 1,
}


class CopyField(BaseModel):
    """One named piece of text in an asset."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    text: str


class Citation(BaseModel):
    """A factual statement in the copy and the sources that support it."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="The statement, copied exactly from a field.")
    references: list[str] = Field(min_length=1, description="Fact IDs or evidence IDs.")


class DraftVariant(BaseModel):
    """One version of an asset as the model writes it."""

    model_config = ConfigDict(extra="forbid")

    fields: list[CopyField] = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)


class ChannelDraft(BaseModel):
    """The model's copy for one channel."""

    model_config = ConfigDict(extra="forbid")

    variants: list[DraftVariant] = Field(default_factory=list)


class CampaignAsset(AssetCopy):
    """An asset plus the statement-level citations behind its references."""

    citations: list[Citation] = Field(default_factory=list)


class CopyRequest(BaseModel):
    """Everything the copywriter needs to write one channel."""

    model_config = ConfigDict(extra="forbid")

    brand: BrandKit
    product: ProductBrief
    strategy: CampaignStrategy
    facts: FactSheet
    findings: list[ResearchFinding] = Field(default_factory=list)
    channel: Channel
    today: date


class ChannelCopy(BaseModel):
    """Assets ready for checking, and any variants that could not be used."""

    assets: list[CampaignAsset] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)


class AssetEdit(BaseModel):
    """A targeted change: replace one exact passage to resolve one issue."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str
    field: str
    find: str = Field(description="The exact passage to replace. It must occur once in the field.")
    replace: str = Field(description="The new text. Leave empty to remove the passage.")
    references: list[str] = Field(
        default_factory=list, description="Sources for any factual statement in the new text."
    )


class RevisionPlan(BaseModel):
    """The edits proposed for one asset."""

    model_config = ConfigDict(extra="forbid")

    edits: list[AssetEdit] = Field(default_factory=list)


class RevisionRequest(BaseModel):
    """An asset, the open issues against it, and the sources available to fix them."""

    model_config = ConfigDict(extra="forbid")

    asset: CampaignAsset
    issues: list[LedgerIssue] = Field(min_length=1)
    brand: BrandKit
    facts: FactSheet
    findings: list[ResearchFinding] = Field(default_factory=list)
    today: date
    required_mentions: dict[str, str] = Field(
        default_factory=dict, description="Names each field must keep."
    )
