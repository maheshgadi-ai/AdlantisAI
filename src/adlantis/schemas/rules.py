"""What the deterministic rules engine reports."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from adlantis.schemas.channels import LimitSeverity
from adlantis.schemas.claims import ClaimType

RuleId = Literal[
    "banned_word",
    "banned_claim_type",
    "health_claim",
    "environmental_claim",
    "superlative_claim",
    "pricing_claim",
    "testimonial_claim",
    "competitor_disparagement",
    "channel_limit",
    "expired_fact",
    "unknown_reference",
]


class RuleViolation(BaseModel):
    """One broken rule at one place in one asset. Errors block it; warnings are reported."""

    rule: RuleId
    severity: LimitSeverity = "error"
    asset_id: str
    field: str | None = None
    quote: str = ""
    start: int | None = Field(default=None, description="Offset in the normalized field text.")
    end: int | None = None
    claim_type: ClaimType | None = None
    message: str
    fix: str


class RuleReport(BaseModel):
    """All violations found, in a stable order."""

    violations: list[RuleViolation] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True when nothing blocks the copy. Warnings do not block."""
        return not self.errors

    @property
    def errors(self) -> list[RuleViolation]:
        """Violations that block the asset."""
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> list[RuleViolation]:
        """Violations reported in the kit that never block."""
        return [v for v in self.violations if v.severity == "warning"]

    def for_rule(self, rule: RuleId) -> list[RuleViolation]:
        """Violations of one rule."""
        return [v for v in self.violations if v.rule == rule]
