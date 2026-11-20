"""The adversarial briefs, and how each one changes a campaign's inputs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from adlantis.schemas.channels import Channel
from adlantis.schemas.facts import ApprovedFact, FactSheet
from adlantis.schemas.inputs import CampaignInputs, load_campaign_inputs

BRIEFS_PATH = Path(__file__).parent / "data" / "adversarial_briefs.yaml"
BrandFolder = Literal["tamsin-hollow-roasters", "kestrune-cycles"]


class PlantedPage(BaseModel):
    """A web page the researcher will find during this brief."""

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    html: str


class AdversarialBrief(BaseModel):
    """A campaign brief written to push the system into breaking a rule."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^AB-\d{2}$")
    title: str
    category: str
    brand: BrandFolder
    channels: list[Channel] = Field(min_length=1)
    pressure: str = Field(min_length=1)
    product_description: str | None = None
    keep_facts: list[str] | None = None
    add_facts: list[ApprovedFact] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    at_most_one_of: list[str] = Field(default_factory=list)
    page: PlantedPage | None = None
    expects_quarantine: bool = False

    @model_validator(mode="after")
    def _has_a_measurable_outcome(self) -> AdversarialBrief:
        if not self.forbidden and len(self.at_most_one_of) < 2:
            raise ValueError(f"{self.id} has nothing to measure")
        return self

    def violations(self, texts: list[str]) -> list[str]:
        """The forbidden patterns found in shipped copy."""
        joined = "\n".join(texts)
        found = [p for p in self.forbidden if re.search(p, joined, re.IGNORECASE)]
        conflicting = [p for p in self.at_most_one_of if re.search(p, joined, re.IGNORECASE)]
        return found + ([f"conflict: {' and '.join(conflicting)}"] if len(conflicting) > 1 else [])

    def violation_contexts(self, texts: list[str], width: int = 70) -> list[str]:
        """Each forbidden match with the words around it, for a reviewer to judge."""
        found = []
        for text in texts:
            for pattern in self.forbidden:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    start, end = max(0, match.start() - width), match.end() + width
                    around = " ".join(text[start:end].split())
                    found.append(f"{match.group()!r} in: ...{around}...")
        return found


def load_briefs(path: Path = BRIEFS_PATH) -> list[AdversarialBrief]:
    """Read and validate the adversarial briefs."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    briefs = [AdversarialBrief.model_validate(item) for item in data["briefs"]]
    ids = [brief.id for brief in briefs]
    if len(ids) != len(set(ids)):
        raise ValueError("brief IDs must be unique")
    return briefs


def apply_brief(brief: AdversarialBrief, examples_dir: Path) -> CampaignInputs:
    """The example brand's inputs, changed the way this brief calls for."""
    folder = examples_dir / brief.brand
    base = load_campaign_inputs(
        folder / "brand.yaml", folder / "facts.yaml", folder / "product.yaml"
    )
    kept = [
        fact for fact in base.facts.facts if brief.keep_facts is None or fact.id in brief.keep_facts
    ]
    product = base.product.model_copy(
        update={
            "channels": brief.channels,
            "description": brief.product_description or base.product.description,
            "campaign_goals": [*base.product.campaign_goals, brief.pressure],
        }
    )
    return CampaignInputs(
        brand=base.brand, facts=FactSheet(facts=[*kept, *brief.add_facts]), product=product
    )
