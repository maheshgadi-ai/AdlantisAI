"""Everything a rule needs to judge one asset."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from adlantis.rules.channels import load_channel_limits
from adlantis.schemas.assets import AssetCopy
from adlantis.schemas.brand import BrandKit
from adlantis.schemas.channels import ChannelLimits
from adlantis.schemas.claims import ClaimType
from adlantis.schemas.facts import ApprovedFact, FactSheet


@dataclass(frozen=True)
class RuleContext:
    """The brand, its facts, and the date. The date is explicit so results are reproducible."""

    brand: BrandKit
    facts: FactSheet
    today: date
    limits: ChannelLimits = field(default_factory=load_channel_limits)
    evidence_ids: frozenset[str] | None = None  # when given, only these may be cited
    product_names: tuple[str, ...] = ()

    @property
    def identifiers(self) -> tuple[str, ...]:
        """Brand and product names, which identify and so never count as claims."""
        return (self.brand.name, *self.brand.aliases, *self.product_names)

    def usable_facts(self, asset: AssetCopy, claim_type: ClaimType) -> list[ApprovedFact]:
        """Facts of this type that the asset cites and that have not expired."""
        cited = (self.facts.get(reference) for reference in asset.references)
        return [
            fact
            for fact in cited
            if fact and fact.claim_type == claim_type and not fact.is_expired(self.today)
        ]
