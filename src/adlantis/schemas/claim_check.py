"""What the claim checker proposes and what code decides."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from adlantis.schemas.claims import ClaimType, ClaimVerdict
from adlantis.schemas.rules import RuleId, RuleViolation


class DraftClaim(BaseModel):
    """One factual claim as the checker model reads it."""

    model_config = ConfigDict(extra="forbid")

    field: str
    quote: str = Field(description="The claim, copied exactly from the field.")
    claim_type: ClaimType
    references: list[str] = Field(default_factory=list)
    verdict: ClaimVerdict
    supporting_passage: str = Field(
        default="", description="The exact passage from the cited source that proves the claim."
    )
    reason: str = Field(min_length=1)
    fix: str = Field(default="", description="A specific, targeted edit when not supported.")


class ClaimCheckDraft(BaseModel):
    """Every claim the checker found in one asset."""

    model_config = ConfigDict(extra="forbid")

    claims: list[DraftClaim] = Field(default_factory=list)


class CheckedClaim(BaseModel):
    """A claim with its final verdict and what decided it."""

    id: str
    asset_id: str
    field: str
    quote: str
    claim_type: ClaimType
    references: list[str] = Field(default_factory=list)
    verdict: ClaimVerdict
    supporting_passage: str = ""
    reason: str
    fix: str = ""
    decided_by: Literal["model", "code"]
    rule: RuleId | None = None


class ClaimCheckResult(BaseModel):
    """The verdicts for one asset, plus rule findings not tied to a single claim."""

    asset_id: str
    claims: list[CheckedClaim] = Field(default_factory=list)
    rule_errors: list[RuleViolation] = Field(default_factory=list)
    warnings: list[RuleViolation] = Field(default_factory=list)

    @property
    def blocked_claims(self) -> list[CheckedClaim]:
        """Claims that keep the asset out of the kit."""
        return [claim for claim in self.claims if claim.verdict != "supported"]

    @property
    def passed(self) -> bool:
        """True when every claim is supported and no rule blocks the asset."""
        return not self.blocked_claims and not self.rule_errors
