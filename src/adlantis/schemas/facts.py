"""The fact sheet (`facts.yaml`): the approved claims a campaign may rely on."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adlantis.schemas.claims import ClaimType

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


class ApprovedFact(BaseModel):
    """One approved claim, its permitted wording, and the evidence behind it."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^F-\d{3}$")
    claim_type: ClaimType
    claim: str = Field(min_length=1)
    wording: Literal["exact", "paraphrase"] = "exact"
    paraphrase_scope: str | None = Field(
        default=None, description="What a rewrite may change and what it must keep."
    )
    approved_phrasings: list[str] = Field(default_factory=list)
    evidence_note: str = Field(min_length=1)
    expires: date | None = None

    @model_validator(mode="after")
    def _wording_rules_are_consistent(self) -> ApprovedFact:
        if self.wording == "exact" and (self.paraphrase_scope or self.approved_phrasings):
            raise ValueError(
                f"{self.id}: exact wording cannot have a paraphrase scope or phrasings"
            )
        if self.wording == "paraphrase" and not self.paraphrase_scope:
            raise ValueError(f"{self.id}: paraphrase wording requires a paraphrase_scope")
        allowed = set(_NUMBER.findall(self.claim))
        for phrasing in self.approved_phrasings:
            invented = sorted(set(_NUMBER.findall(phrasing)) - allowed)
            if invented:
                raise ValueError(f"{self.id}: phrasing adds numbers not in the claim: {invented}")
        return self

    @property
    def wordings(self) -> tuple[str, ...]:
        """Every wording that may appear verbatim in copy."""
        return (self.claim, *self.approved_phrasings)

    def is_expired(self, today: date) -> bool:
        """True after the expiry date. A fact is still valid on the day it expires."""
        return self.expires is not None and today > self.expires


class FactSheet(BaseModel):
    """All approved facts for a brand."""

    model_config = ConfigDict(extra="forbid")

    facts: list[ApprovedFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> FactSheet:
        ids = [fact.id for fact in self.facts]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate fact IDs: {duplicates}")
        return self

    def get(self, fact_id: str) -> ApprovedFact | None:
        """The fact with this ID, if any."""
        return next((fact for fact in self.facts if fact.id == fact_id), None)
