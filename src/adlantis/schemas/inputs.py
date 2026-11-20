"""Load and cross-check the three campaign input files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from adlantis.schemas.brand import BrandKit
from adlantis.schemas.facts import FactSheet
from adlantis.schemas.product import ProductBrief

ModelT = TypeVar("ModelT", bound=BaseModel)


class InputFileError(ValueError):
    """Raised when an input file is missing, malformed, or inconsistent."""


class CampaignInputs(BaseModel):
    """A brand kit, fact sheet, and product brief that agree with each other."""

    model_config = ConfigDict(extra="forbid")

    brand: BrandKit
    facts: FactSheet
    product: ProductBrief

    @model_validator(mode="after")
    def _inputs_agree(self) -> CampaignInputs:
        problems: list[str] = []
        for fact in self.facts.facts:
            if fact.claim_type in self.brand.banned_claim_types:
                problems.append(f"{fact.id} has banned claim type {fact.claim_type!r}")
            for word in self.brand.banned_words:
                if any(_mentions(word, wording) for wording in fact.wordings):
                    problems.append(f"{fact.id} uses banned word {word!r}")
        brand_name = self.brand.name.casefold()
        for competitor in self.brand.competitors:
            if brand_name in {name.casefold() for name in competitor.names}:
                problems.append(f"competitor {competitor.name!r} is the brand itself")
        if problems:
            raise ValueError("; ".join(problems))
        return self


def _mentions(word: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) is not None


def load_yaml_model(path: Path, model: type[ModelT]) -> ModelT:
    """Read a YAML file into `model`.

    Raises:
        InputFileError: If the file is missing, is not valid YAML, or fails validation.
    """
    try:
        return model.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise InputFileError(f"Input file not found: {path}") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise InputFileError(f"Invalid {model.__name__} in {path}: {exc}") from exc


def load_campaign_inputs(brand: Path, facts: Path, product: Path) -> CampaignInputs:
    """Load all three input files and check that they agree.

    Raises:
        InputFileError: If any file is invalid or the files contradict each other.
    """
    loaded = {
        "brand": load_yaml_model(brand, BrandKit),
        "facts": load_yaml_model(facts, FactSheet),
        "product": load_yaml_model(product, ProductBrief),
    }
    try:
        return CampaignInputs(**loaded)
    except ValidationError as exc:
        raise InputFileError(f"Inconsistent campaign inputs: {exc}") from exc
