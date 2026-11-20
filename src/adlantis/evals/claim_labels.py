"""The hand-labeled claim-extraction set."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from adlantis.schemas.channels import Channel
from adlantis.schemas.claims import ClaimType

CLAIM_LABELS_PATH = Path(__file__).parent / "data" / "claim_extraction.yaml"


class LabeledClaim(BaseModel):
    """One claim a careful reader would extract."""

    model_config = ConfigDict(extra="forbid")

    quote: str = Field(min_length=1)
    claim_type: ClaimType


class LabeledSnippet(BaseModel):
    """A piece of copy and every claim in it."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^CE-\d{3}$")
    brand: str
    channel: Channel
    text: str = Field(min_length=1)
    claims: list[LabeledClaim]

    @model_validator(mode="after")
    def _quotes_come_from_the_text(self) -> LabeledSnippet:
        missing = [claim.quote for claim in self.claims if claim.quote not in self.text]
        if missing:
            raise ValueError(f"{self.id}: quotes not found in the text: {missing}")
        return self


class ClaimLabelSet(BaseModel):
    """All labeled snippets."""

    model_config = ConfigDict(extra="forbid")

    snippets: list[LabeledSnippet]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> ClaimLabelSet:
        ids = [snippet.id for snippet in self.snippets]
        if len(ids) != len(set(ids)):
            raise ValueError("snippet IDs must be unique")
        return self


def load_claim_labels(path: Path = CLAIM_LABELS_PATH) -> ClaimLabelSet:
    """Read and validate the labeled set."""
    return ClaimLabelSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
